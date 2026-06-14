"""Answers grounded in the latest stored portal-run evidence bundle: alert
explanation, status meaning, and next-step recommendation."""

from __future__ import annotations

from ..schemas import AgentAnswer, Citation, Intent
from ..tools import ToolRegistry


def _answer_from_latest_evidence(active_registry: ToolRegistry, intent: Intent) -> AgentAnswer:
    try:
        spec = active_registry.assert_can_call("read_evidence_bundle")
    except (KeyError, PermissionError) as error:
        return AgentAnswer(
            intent=intent,
            answer=f"I cannot read local evidence for this answer: {type(error).__name__}: {error}",
            confidence="uncertain",
            tool_calls=("read_evidence_bundle",),
            uncertain=True,
        )
    if spec.handler is None:
        return AgentAnswer(
            intent=intent,
            answer="This answer needs a local evidence bundle. Run with a configured LifeAgent home or create a portal/email evidence run first.",
            confidence="uncertain",
            tool_calls=("read_evidence_bundle",),
            uncertain=True,
        )
    try:
        result = active_registry.call("read_evidence_bundle")
    except Exception as error:
        return AgentAnswer(
            intent=intent,
            answer=f"I could not read the local evidence bundle: {type(error).__name__}: {error}",
            confidence="uncertain",
            tool_calls=("read_evidence_bundle",),
            uncertain=True,
        )
    runs = list(result.get("runs") or []) if isinstance(result, dict) else []
    if not runs:
        return AgentAnswer(
            intent=intent,
            answer="I cannot answer from evidence yet because no local runs are stored.",
            confidence="uncertain",
            tool_calls=("read_evidence_bundle",),
            uncertain=True,
        )
    latest = runs[0]
    alert = latest.get("alert", {}) or {}
    health = latest.get("health", {}) or {}
    status = latest.get("status", {}) or {}
    deadlines = list(latest.get("deadlines") or [])
    evidence = latest.get("evidence", {}) or {}
    run_id = str(latest.get("run_id") or "")
    alert_level = str(alert.get("level") or "unknown")
    alert_reason = str(alert.get("reason") or "No alert reason was recorded.")
    status_value = str(status.get("value") or "unknown")
    health_state = str(health.get("state") or "unknown")
    deadline_summary = _deadline_summary(deadlines)
    citation = Citation(
        source_id=run_id,
        source_type="portal_run",
        evidence=str(evidence.get("redacted_path") or evidence.get("path") or ""),
        captured_at=str(latest.get("captured_at") or ""),
    )
    metadata = {
        "run_id": run_id,
        "alert_level": alert_level,
        "alert_reason": alert_reason,
        "status": status_value,
        "health_state": health_state,
        "deadline_count": len(deadlines),
    }
    uncertain = alert_level == "uncertain" or health_state in {"uncertain", "capture_error", "captcha", "session_expired"}

    if intent == Intent.ALERT_EXPLANATION:
        return AgentAnswer(
            intent=intent,
            answer=(
                f"Latest alert {run_id} is {alert_level}: {alert_reason} "
                f"Status={status_value}; health={health_state}.{deadline_summary}"
            ),
            confidence="uncertain" if uncertain else "high",
            citations=(citation,),
            tool_calls=("read_evidence_bundle",),
            uncertain=uncertain,
            metadata=metadata,
        )
    if intent == Intent.STATUS_MEANING:
        return AgentAnswer(
            intent=intent,
            answer=(
                f"Latest status is {status_value}. {_status_meaning(status_value, health_state)} "
                f"Alert={alert_level}; health={health_state}.{deadline_summary}"
            ),
            confidence="uncertain" if uncertain or status_value == "unknown" else "medium",
            citations=(citation,),
            tool_calls=("read_evidence_bundle",),
            uncertain=uncertain or status_value == "unknown",
            metadata=metadata,
        )
    next_step, recommended_tools, requires_confirmation = _next_step_for_run(
        alert_level=alert_level,
        status_value=status_value,
        health_state=health_state,
        deadlines=deadlines,
    )
    metadata["recommended_tools"] = recommended_tools
    return AgentAnswer(
        intent=intent,
        answer=f"Recommended next step: {next_step}",
        confidence="uncertain" if uncertain else "medium",
        citations=(citation,),
        tool_calls=("read_evidence_bundle",),
        requires_confirmation=requires_confirmation,
        uncertain=uncertain,
        metadata=metadata,
    )


def _deadline_summary(deadlines: list[object]) -> str:
    if not deadlines:
        return ""
    first = deadlines[0] if isinstance(deadlines[0], dict) else {}
    date_text = str(first.get("date_text") or "").strip()
    if not date_text:
        return ""
    return f" Latest deadline candidate: {date_text}."


def _status_meaning(status_value: str, health_state: str) -> str:
    normalized = status_value.lower()
    if health_state != "ok":
        return "The current state is not fully verified, so treat this as a prompt to manually check the official source."
    if normalized in {"action_required", "written_notice_required", "rent_due"}:
        return "This is an action-required state; review the cited evidence and handle the deadline or payment before relying on automation."
    if normalized in {"submitted", "pending", "current"}:
        return "This indicates no immediate action marker was detected in the latest capture, but it should still be monitored for changes."
    if normalized in {"approved", "complete", "completed"}:
        return "This looks like a positive or terminal state in the latest capture; keep the evidence for records."
    if normalized in {"appointment_available", "slot_available"}:
        return "This indicates an available appointment or slot; act quickly only after confirming the official page."
    return "This status is not mapped to a confident domain meaning yet; use the cited evidence and official source before acting."


def _next_step_for_run(
    *,
    alert_level: str,
    status_value: str,
    health_state: str,
    deadlines: list[object],
) -> tuple[str, list[str], bool]:
    normalized = status_value.lower()
    if health_state != "ok" or alert_level == "uncertain":
        return (
            "manually open the official source because the latest capture is uncertain, then re-run verification after the page is readable.",
            ["capture_latest_portal"],
            False,
        )
    deadline_text = _first_deadline_text(deadlines)
    deadline_action = f" before {deadline_text}" if deadline_text else ""
    if alert_level in {"critical", "warning"} or normalized in {"action_required", "written_notice_required", "rent_due"}:
        return (
            f"review the cited evidence, complete the required action{deadline_action}, then draft a calendar reminder; external calendar sync still needs confirmation.",
            ["read_evidence_bundle", "draft_calendar_event"],
            True,
        )
    if deadlines:
        return (
            f"keep the deadline visible before {deadline_text}. Draft or review the local calendar event before any external sync.",
            ["read_evidence_bundle", "draft_calendar_event"],
            True,
        )
    return (
        "no immediate action is verified; keep monitoring and ingest new email or portal evidence when it arrives.",
        ["read_evidence_bundle"],
        False,
    )


def _first_deadline_text(deadlines: list[object]) -> str:
    if not deadlines:
        return ""
    first = deadlines[0] if isinstance(deadlines[0], dict) else {}
    return str(first.get("date_text") or "").strip()
