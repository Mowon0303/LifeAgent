"""The intent dispatcher: route a question to the right tool-first answer path.

The per-intent answer logic lives in the sibling modules (facts, general, portal,
runs, policy); this file only classifies intent and delegates.
"""

from __future__ import annotations

from sentineldesk.email.extract import extract_email_facts, find_messages
from sentineldesk.email.models import EmailMessage

from ..conflict import detect_fact_conflict
from ..router import classify_intent
from ..schemas import AgentAnswer, Citation, Intent
from ..tools import ToolRegistry, default_tool_registry
from .facts import _latest_global_answer, _task_overview_answer
from .general import _general_answer
from .policy import _answer_policy_question
from .portal import _portal_trigger_citations, _should_verify_portal, _verify_deadline_from_portal
from .runs import _answer_from_latest_evidence


def answer_question(
    question: str,
    *,
    messages: list[EmailMessage] | None = None,
    registry: ToolRegistry | None = None,
    previous_intent: str | None = None,
    intent_override: Intent | None = None,
    general_mode: str | None = None,
    calendar: list[dict] | None = None,
) -> AgentAnswer:
    active_registry = registry or default_tool_registry()
    # intent_override carries the workflow's LLM-resolved intent; without it we
    # use the deterministic keyword router (the path direct/test callers take).
    intent = intent_override or classify_intent(question, previous_intent=previous_intent)

    if intent in {Intent.LATEST_DEADLINE, Intent.LATEST_AMOUNT}:
        active_registry.assert_can_call("search_latest_email")
        tool_calls = ["search_latest_email"]
        wanted = "deadline" if intent == Intent.LATEST_DEADLINE else "amount"
        keyword_matches = [
            fact
            for message in find_messages(messages or [], question, limit=10)
            for fact in extract_email_facts(message)
            if fact.kind == wanted
        ]
        # A narrow, specific query ("when is my rent due") keyword-matches a few
        # emails about the same obligation — keep the conflict-aware path there.
        # A broad query ("latest deadline"), a cross-language one, or a keyword
        # miss instead needs every deadline on file: scan all messages and answer
        # with the single nearest/latest, never a false "conflict" across
        # unrelated items or a guessed portal.
        narrow = bool(keyword_matches) and len({fact.source_id for fact in keyword_matches}) <= 3
        if not narrow:
            global_matches = [
                fact
                for message in messages or []
                for fact in extract_email_facts(message)
                if fact.kind == wanted
            ]
            if global_matches:
                return _latest_global_answer(
                    global_matches, wanted=wanted, intent=intent, tool_calls=tool_calls
                )
            if wanted == "deadline" and _should_verify_portal(messages or []):
                portal_answer = _verify_deadline_from_portal(
                    active_registry,
                    tool_calls=tool_calls,
                    trigger_citations=_portal_trigger_citations(messages or []),
                )
                if portal_answer is not None:
                    return portal_answer
            return AgentAnswer(
                intent=intent,
                answer="I cannot verify the latest fact from available email evidence.",
                confidence="uncertain",
                tool_calls=tuple(tool_calls),
                uncertain=True,
            )
        matches = keyword_matches
        conflict = detect_fact_conflict(matches, wanted)
        if conflict.has_conflict:
            citations = tuple(
                Citation(
                    source_id=fact.source_id,
                    source_type=fact.source_type,
                    evidence=fact.evidence,
                    captured_at=fact.received_at,
                )
                for fact in conflict.facts
            )
            safest = f" Safest earlier candidate: {conflict.safest_value}." if conflict.safest_value else ""
            return AgentAnswer(
                intent=intent,
                answer=f"Conflicting {wanted} evidence found: {', '.join(conflict.values)}.{safest} Verify before acting.",
                confidence="uncertain",
                citations=citations,
                tool_calls=tuple(tool_calls),
                uncertain=True,
                metadata={"conflict_kind": wanted},
            )
        best = sorted(matches, key=lambda fact: (fact.confidence, fact.received_at), reverse=True)[0]
        return AgentAnswer(
            intent=intent,
            answer=f"Verified {wanted}: {best.value}",
            confidence="high" if best.confidence >= 0.75 else "medium",
            citations=(
                Citation(
                    source_id=best.source_id,
                    source_type=best.source_type,
                    evidence=best.evidence,
                    captured_at=best.received_at,
                ),
            ),
            tool_calls=tuple(tool_calls),
        )

    if intent == Intent.TASK_OVERVIEW:
        active_registry.assert_can_call("search_latest_email")
        return _task_overview_answer(calendar or [])

    if intent == Intent.CALENDAR_ACTION:
        active_registry.assert_can_call("draft_calendar_event")
        return AgentAnswer(
            intent=intent,
            answer="I can draft a calendar event, but external calendar sync requires explicit confirmation.",
            confidence="medium",
            tool_calls=("draft_calendar_event",),
            requires_confirmation=True,
        )

    if intent == Intent.PAGE_CHANGE:
        spec = active_registry.assert_can_call("capture_latest_portal")
        if spec.handler is not None:
            try:
                result = active_registry.call("capture_latest_portal")
            except Exception as error:
                return AgentAnswer(
                    intent=intent,
                    answer=f"I could not verify the portal state: {type(error).__name__}: {error}",
                    confidence="uncertain",
                    tool_calls=("capture_latest_portal",),
                    uncertain=True,
                )
            runs = list(result.get("runs") or []) if isinstance(result, dict) else []
            if not runs:
                return AgentAnswer(
                    intent=intent,
                    answer="I could not verify the portal state because no configured target ran.",
                    confidence="uncertain",
                    tool_calls=("capture_latest_portal",),
                    uncertain=True,
                )
            latest = runs[0]
            alert = latest.get("alert", {})
            status = latest.get("status", {})
            evidence = latest.get("evidence", {})
            alert_level = str(alert.get("level") or "unknown")
            status_value = str(status.get("value") or "unknown")
            return AgentAnswer(
                intent=intent,
                answer=f"Verified portal capture {latest.get('run_id')}: alert={alert_level}, status={status_value}.",
                confidence="uncertain" if alert_level == "uncertain" else "medium",
                citations=(
                    Citation(
                        source_id=str(latest.get("run_id") or ""),
                        source_type="portal_run",
                        evidence=str(evidence.get("path") or ""),
                        captured_at=str(latest.get("captured_at") or ""),
                    ),
                ),
                tool_calls=("capture_latest_portal",),
                uncertain=alert_level == "uncertain",
                metadata={
                    "run_id": str(latest.get("run_id") or ""),
                    "alert_level": alert_level,
                    "status": status_value,
                    "evidence_path": str(evidence.get("path") or ""),
                },
            )
        return AgentAnswer(
            intent=intent,
            answer="Page-change questions should run the deterministic monitor core, not RAG.",
            confidence="medium",
            tool_calls=("capture_latest_portal",),
        )

    if intent in {Intent.ALERT_EXPLANATION, Intent.STATUS_MEANING, Intent.NEXT_STEP_RECOMMENDATION}:
        return _answer_from_latest_evidence(active_registry, intent)

    if intent == Intent.POLICY_QUESTION:
        return _answer_policy_question(active_registry, question)

    return _general_answer(question, active_registry, general_mode=general_mode)
