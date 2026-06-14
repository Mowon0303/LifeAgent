from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sentineldesk import db
from sentineldesk.config import Paths
from sentineldesk.email.models import EmailMessage

from .graph import answer_question
from .llm import ChatClient, chat_client_for, refine_answer
from .memory import build_memory
from .model import ModelProvider
from .router import classify_intent, is_greeting, llm_route_label, _LLM_LABEL_INTENT, _continue_intent
from .schemas import AgentAnswer, Intent
from .tools import ToolRegistry


@dataclass(frozen=True)
class WorkflowRuntime:
    engine: str
    reason: str


def runtime_for(provider: ModelProvider) -> WorkflowRuntime:
    if provider.langgraph_available:
        return WorkflowRuntime("langgraph", "langgraph_available")
    return WorkflowRuntime("rule_graph", "langgraph_unavailable")


def answer_with_workflow(
    question: str,
    *,
    provider: ModelProvider,
    messages: list[EmailMessage] | None = None,
    registry: ToolRegistry | None = None,
    paths: Paths | None = None,
    chat_client: ChatClient | None = None,
    history: list[dict[str, Any]] | None = None,
) -> AgentAnswer:
    runtime = runtime_for(provider)
    resolved_client = chat_client if chat_client is not None else chat_client_for(provider)
    # Budgeted conversation memory: recent turns verbatim + a compacted gist of
    # older ones. Reference only — facts are re-derived each turn and stay guarded.
    memory_block = build_memory(history).as_prompt_block()
    initial_state = {
        "question": question,
        "messages": messages or [],
        "registry": registry,
        "previous_intent": _previous_intent(history),
        "chat_client": resolved_client,  # the route stage uses it for LLM intent fallback
        "memory_block": memory_block,
    }
    answer: AgentAnswer | None = None
    if runtime.engine == "langgraph":
        runnable = build_langgraph_workflow()
        if runnable is not None:
            result = runnable.invoke(initial_state)
            candidate = result.get("answer") if isinstance(result, dict) else None
            if isinstance(candidate, AgentAnswer):
                answer = _annotate_answer(candidate, runtime=runtime, provider=provider, state=result if isinstance(result, dict) else {})
    if answer is None:
        state = _run_rule_workflow(initial_state)
        answer = _annotate_answer(state["answer"], runtime=runtime, provider=provider, state=state)
    return _refine_stage(
        answer, question=question, provider=provider, paths=paths,
        chat_client=chat_client, context=memory_block,
    )


def _refine_stage(
    answer: AgentAnswer,
    *,
    question: str,
    provider: ModelProvider,
    paths: Paths | None,
    chat_client: ChatClient | None,
    context: str = "",
) -> AgentAnswer:
    refined, call_record = refine_answer(
        answer, question=question, provider=provider, client=chat_client, context=context
    )
    if call_record is None:
        return refined
    refined.metadata["model_call"] = call_record.to_dict()
    trace = list(refined.metadata.get("workflow_trace") or [])
    trace.append({"stage": "refine", "status": call_record.status, "model": call_record.model})
    refined.metadata["workflow_trace"] = trace
    if paths is not None:
        db.init_db(paths)
        db.insert_model_call(paths, **call_record.to_dict())
    return refined


def _annotate_answer(
    answer: AgentAnswer,
    *,
    runtime: WorkflowRuntime,
    provider: ModelProvider,
    state: dict[str, Any],
) -> AgentAnswer:
    answer.metadata["workflow_engine"] = runtime.engine
    answer.metadata["model_provider"] = provider.provider
    answer.metadata["model"] = provider.model
    answer.metadata["workflow_trace"] = list(state.get("workflow_trace") or [])
    initial_plan = list(state.get("planned_tools") or [])
    answer.metadata["planned_tools_initial"] = initial_plan
    answer.metadata["planned_tools"] = _merge_tools(initial_plan, list(answer.tool_calls))
    return answer


def _run_rule_workflow(state: dict[str, Any]) -> dict[str, Any]:
    state = _route_stage(dict(state))
    state = _tool_stage(state)
    state = _finalize_stage(state)
    return state


def build_langgraph_workflow() -> Any | None:
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        return None

    graph = StateGraph(dict)
    graph.add_node("route", _route_stage)
    graph.add_node("tools", _tool_stage)
    graph.add_node("finalize", _finalize_stage)
    graph.set_entry_point("route")
    graph.add_edge("route", "tools")
    graph.add_edge("tools", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def _previous_intent(history: list[dict[str, Any]] | None) -> str | None:
    """The intent of the most recent prior turn, used to resolve a follow-up
    like "其他的呢" against what was just asked."""
    for turn in reversed(history or []):
        if isinstance(turn, dict) and turn.get("intent"):
            return str(turn.get("intent"))
    return None


def _route_stage(state: dict[str, Any]) -> dict[str, Any]:
    question = str(state.get("question") or "")
    previous_intent = state.get("previous_intent")
    intent = classify_intent(question, previous_intent=previous_intent)
    general_mode = None
    routed_by = "keyword"
    # Keyword pass is the fast deterministic default. Only when it gives up (GENERAL,
    # and not a greeting) do we ask the model — which generalizes to any phrasing.
    if intent == Intent.GENERAL and not is_greeting(question):
        label = llm_route_label(
            question, client=state.get("chat_client"), previous_intent=previous_intent,
            context=str(state.get("memory_block") or ""),
        )
        if label in _LLM_LABEL_INTENT:
            intent = _LLM_LABEL_INTENT[label]
            routed_by = "llm"
        elif label == "search":
            general_mode = "search"  # a real email-content question -> RAG
            routed_by = "llm"
        else:
            # The model couldn't place it (or no model). If we were just talking about
            # the user's tasks, a short unplaceable follow-up like "比如呢"/"其他事都是什么"
            # means "go on / which ones" — continue the overview rather than dump a
            # generic blurb. (No honest-menu fallback: a non-answer reads as a bug.)
            continued = _continue_intent(previous_intent or "")
            if continued is not None:
                intent = continued
                routed_by = "continue"
    state["intent"] = intent.value
    state["general_mode"] = general_mode
    _append_trace(state, "route", {"intent": intent.value, "routed_by": routed_by, "general_mode": general_mode})
    return state


def _tool_stage(state: dict[str, Any]) -> dict[str, Any]:
    planned_tools = _planned_tools_for_intent(str(state.get("intent") or ""))
    state["planned_tools"] = planned_tools
    _append_trace(state, "tools", {"planned_tools": planned_tools})
    return state


def _finalize_stage(state: dict[str, Any]) -> dict[str, Any]:
    intent_value = state.get("intent")
    answer = answer_question(
        str(state.get("question") or ""),
        messages=list(state.get("messages") or []),
        registry=state.get("registry"),
        previous_intent=state.get("previous_intent"),
        intent_override=Intent(intent_value) if intent_value else None,
        general_mode=state.get("general_mode"),
    )
    state["answer"] = answer
    _append_trace(state, "finalize", {"confidence": answer.confidence, "uncertain": answer.uncertain})
    return state


def _append_trace(state: dict[str, Any], stage: str, metadata: dict[str, Any]) -> None:
    trace = list(state.get("workflow_trace") or [])
    trace.append({"stage": stage, **metadata})
    state["workflow_trace"] = trace


def _merge_tools(planned: list[str], actual: list[str]) -> list[str]:
    merged = list(planned)
    for tool in actual:
        if tool not in merged:
            merged.append(tool)
    return merged


def _planned_tools_for_intent(intent: str) -> list[str]:
    if intent in {"latest_deadline", "latest_amount", "task_overview"}:
        return ["search_latest_email"]
    if intent == "calendar_action":
        return ["draft_calendar_event"]
    if intent == "page_change":
        return ["capture_latest_portal"]
    if intent == "alert_explanation":
        return ["read_evidence_bundle"]
    if intent == "status_meaning":
        return ["read_evidence_bundle"]
    if intent == "next_step_recommendation":
        return ["read_evidence_bundle"]
    if intent == "policy_question":
        return ["search_policy_docs"]
    return []
