"""Email-to-portal deadline verification: detect portal-login triggers in email
evidence and fall back to a deterministic portal capture when no email fact answers."""

from __future__ import annotations

# The pipeline's own reader, on purpose: it strips markup and quoted replies,
# and re-implementing that here is how the two drifted apart in the first place.
from sentineldesk.email.extract import _subject_body_text
from sentineldesk.email.extract_patterns import SECURITY_NOTIFICATION_RE, STRONG_DEADLINE_CUE_RE
from sentineldesk.email.models import EmailMessage

from ..schemas import AgentAnswer, Citation, Intent
from ..tools import ToolRegistry


PORTAL_TERMS = ("log in", "login", "sign in", "portal", "view online", "view your account", "account center")


def _message_text(message: EmailMessage) -> str:
    """Readable text, the same way the extraction pipeline reads a message.

    Joining ``body_text`` raw put ``<!DOCTYPE html><html lang="en" xmlns=...``
    into citation evidence, so drilling into a cited source showed markup
    instead of the sentence that justified the citation.
    """
    parts = [_subject_body_text(message)]
    parts.extend(str(item) for item in message.attachment_texts)
    return " ".join(part for part in parts if part)


def _should_verify_portal(messages: list[EmailMessage]) -> bool:
    return any(_is_portal_trigger(message) for message in messages)


def _is_portal_trigger(message: EmailMessage) -> bool:
    """Does this message actually say "the deadline lives in the portal"?

    Matching "sign in" alone made every security alert a portal trigger. A real
    mailbox is full of "New sign-in to your OpenAI account", and each one pushed
    a deadline question onto the portal path and then cited itself -- four
    citations, none of them containing a deadline. So a trigger now needs both
    halves: a way in *and* something dated to go in for. Security notifications
    are excluded outright; they are reporting a sign-in that already happened,
    not asking for one.
    """
    text = _message_text(message)
    if not any(term in text.lower() for term in PORTAL_TERMS):
        return False
    if SECURITY_NOTIFICATION_RE.search(text):
        return False
    return bool(STRONG_DEADLINE_CUE_RE.search(text))


def _portal_trigger_citations(messages: list[EmailMessage]) -> tuple[Citation, ...]:
    return tuple(
        Citation(
            source_id=message.source_id,
            source_type=message.source_type,
            evidence=_portal_trigger_evidence(message),
            captured_at=message.received_at,
        )
        for message in messages
        if _is_portal_trigger(message)
    )


def _contains_portal_trigger(text: str) -> bool:
    return any(term in text.lower() for term in PORTAL_TERMS)


def _portal_trigger_evidence(message: EmailMessage, *, limit: int = 220) -> str:
    cleaned = " ".join(_message_text(message).split())
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
