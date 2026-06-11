from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sentineldesk.email.models import EmailMessage

from .graph import answer_question
from .model import ModelProvider
from .router import classify_intent
from .schemas import AgentAnswer
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
) -> AgentAnswer:
    runtime = runtime_for(provider)
    initial_state = {"question": question, "messages": messages or [], "registry": registry}
    if runtime.engine == "langgraph":
        runnable = build_langgraph_workflow()
        if runnable is not None:
            result = runnable.invoke(initial_state)
            answer = result.get("answer") if isinstance(result, dict) else None
            if isinstance(answer, AgentAnswer):
                return _annotate_answer(answer, runtime=runtime, provider=provider, state=result if isinstance(result, dict) else {})
    state = _run_rule_workflow(initial_state)
    answer = state["answer"]
    return _annotate_answer(answer, runtime=runtime, provider=provider, state=state)


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


def _route_stage(state: dict[str, Any]) -> dict[str, Any]:
    intent = classify_intent(str(state.get("question") or ""))
    state["intent"] = intent.value
    _append_trace(state, "route", {"intent": intent.value})
    return state


def _tool_stage(state: dict[str, Any]) -> dict[str, Any]:
    planned_tools = _planned_tools_for_intent(str(state.get("intent") or ""))
    state["planned_tools"] = planned_tools
    _append_trace(state, "tools", {"planned_tools": planned_tools})
    return state


def _finalize_stage(state: dict[str, Any]) -> dict[str, Any]:
    answer = answer_question(
        str(state.get("question") or ""),
        messages=list(state.get("messages") or []),
        registry=state.get("registry"),
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
    if intent in {"latest_deadline", "latest_amount"}:
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
