"""Email-to-portal deadline verification: detect portal-login triggers in email
evidence and fall back to a deterministic portal capture when no email fact answers."""

from __future__ import annotations

from sentineldesk.email.models import EmailMessage

from ..schemas import AgentAnswer, Citation, Intent
from ..tools import ToolRegistry


def _should_verify_portal(messages: list[EmailMessage]) -> bool:
    terms = ("log in", "login", "sign in", "portal", "view online", "view your account", "account center")
    for message in messages:
        text = " ".join([message.subject, message.body_text, *message.attachment_texts]).lower()
        if any(term in text for term in terms):
            return True
    return False


def _portal_trigger_citations(messages: list[EmailMessage]) -> tuple[Citation, ...]:
    citations: list[Citation] = []
    for message in messages:
        text = " ".join([message.subject, message.body_text, *message.attachment_texts]).lower()
        if not _contains_portal_trigger(text):
            continue
        citations.append(
            Citation(
                source_id=message.source_id,
                source_type=message.source_type,
                evidence=_portal_trigger_evidence(message),
                captured_at=message.received_at,
            )
        )
    return tuple(citations)


def _contains_portal_trigger(text: str) -> bool:
    terms = ("log in", "login", "sign in", "portal", "view online", "view your account", "account center")
    return any(term in text for term in terms)


def _portal_trigger_evidence(message: EmailMessage, *, limit: int = 220) -> str:
    text = " ".join([message.subject, message.body_text, *message.attachment_texts])
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _verify_deadline_from_portal(
    active_registry: ToolRegistry,
    *,
    tool_calls: list[str],
    trigger_citations: tuple[Citation, ...] = (),
) -> AgentAnswer | None:
    try:
        spec = active_registry.assert_can_call("capture_latest_portal")
    except (KeyError, PermissionError):
        return None
    if spec.handler is None:
        return None
    portal_tool_calls = [*tool_calls, "capture_latest_portal"]
    try:
        result = active_registry.call("capture_latest_portal")
    except Exception as error:
        return AgentAnswer(
            intent=Intent.LATEST_DEADLINE,
            answer=f"Email points to a portal, but I could not verify the portal deadline: {type(error).__name__}: {error}",
            confidence="uncertain",
            citations=trigger_citations,
            tool_calls=tuple(portal_tool_calls),
            uncertain=True,
            metadata=_portal_fallback_metadata(trigger_citations, fallback_error=f"{type(error).__name__}: {error}"),
        )
    runs = list(result.get("runs") or []) if isinstance(result, dict) else []
    if not runs:
        return AgentAnswer(
            intent=Intent.LATEST_DEADLINE,
            answer="Email points to a portal, but no configured portal target ran.",
            confidence="uncertain",
            citations=trigger_citations,
            tool_calls=tuple(portal_tool_calls),
            uncertain=True,
            metadata=_portal_fallback_metadata(trigger_citations, fallback_error="no_configured_portal_target"),
        )
    latest = runs[0]
    deadlines = list(latest.get("deadlines") or [])
    portal_citation = _portal_run_citation(latest)
    citations = (portal_citation, *trigger_citations)
    metadata = _portal_fallback_metadata(trigger_citations, latest=latest, deadlines=deadlines)
    if not deadlines:
        return AgentAnswer(
            intent=Intent.LATEST_DEADLINE,
            answer=f"Email points to a portal, but portal capture {latest.get('run_id')} did not expose a deadline.",
            confidence="uncertain",
            citations=citations,
            tool_calls=tuple(portal_tool_calls),
            uncertain=True,
            metadata=metadata,
        )
    deadline = deadlines[0]
    alert = latest.get("alert", {}) if isinstance(latest.get("alert"), dict) else {}
    health = latest.get("health", {}) if isinstance(latest.get("health"), dict) else {}
    alert_level = str(alert.get("level") or "")
    uncertain = alert_level == "uncertain" or str(health.get("state") or "") != "ok"
    answer = (
        f"Verified deadline from portal capture: {deadline.get('date_text')}"
        if not uncertain
        else f"Portal capture found deadline candidate {deadline.get('date_text')}, but verification is uncertain. Check the official portal before acting."
    )
    return AgentAnswer(
        intent=Intent.LATEST_DEADLINE,
        answer=answer,
        confidence="uncertain" if uncertain else "medium",
        citations=citations,
        tool_calls=tuple(portal_tool_calls),
        uncertain=uncertain,
        metadata=metadata,
    )


def _portal_run_citation(latest: dict[str, object]) -> Citation:
    evidence = latest.get("evidence", {}) if isinstance(latest.get("evidence"), dict) else {}
    return Citation(
        source_id=str(latest.get("run_id") or ""),
        source_type="portal_run",
        evidence=str(evidence.get("redacted_path") or evidence.get("path") or ""),
        captured_at=str(latest.get("captured_at") or ""),
    )


def _portal_fallback_metadata(
    trigger_citations: tuple[Citation, ...],
    *,
    latest: dict[str, object] | None = None,
    deadlines: list[object] | None = None,
    fallback_error: str = "",
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "fallback": "email_to_portal_deadline",
        "fallback_reason": "email_requested_portal_login",
        "fallback_email_source_ids": [citation.source_id for citation in trigger_citations],
        "fallback_email_count": len(trigger_citations),
        "verification_source": "portal_run",
    }
    if fallback_error:
        metadata["fallback_error"] = fallback_error
    if latest is None:
        return metadata
    alert = latest.get("alert", {}) if isinstance(latest.get("alert"), dict) else {}
    status = latest.get("status", {}) if isinstance(latest.get("status"), dict) else {}
    health = latest.get("health", {}) if isinstance(latest.get("health"), dict) else {}
    evidence = latest.get("evidence", {}) if isinstance(latest.get("evidence"), dict) else {}
    metadata.update(
        {
            "run_id": str(latest.get("run_id") or ""),
            "portal_run_id": str(latest.get("run_id") or ""),
            "portal_alert_level": str(alert.get("level") or ""),
            "alert_level": str(alert.get("level") or ""),
            "portal_status": str(status.get("value") or ""),
            "portal_health_state": str(health.get("state") or ""),
            "portal_deadline_count": len(deadlines or []),
            "evidence_path": str(evidence.get("redacted_path") or evidence.get("path") or ""),
        }
    )
    return metadata
