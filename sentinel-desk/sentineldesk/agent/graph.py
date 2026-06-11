from __future__ import annotations

from sentineldesk.email.extract import extract_email_facts, find_messages
from sentineldesk.email.models import EmailMessage

from .conflict import detect_fact_conflict
from .router import classify_intent
from .schemas import AgentAnswer, Citation, Intent
from .tools import ToolRegistry, default_tool_registry


def answer_question(
    question: str,
    *,
    messages: list[EmailMessage] | None = None,
    registry: ToolRegistry | None = None,
) -> AgentAnswer:
    active_registry = registry or default_tool_registry()
    intent = classify_intent(question)

    if intent in {Intent.LATEST_DEADLINE, Intent.LATEST_AMOUNT}:
        active_registry.assert_can_call("search_latest_email")
        tool_calls = ["search_latest_email"]
        facts = []
        for message in find_messages(messages or [], question, limit=10):
            facts.extend(extract_email_facts(message))
        wanted = "deadline" if intent == Intent.LATEST_DEADLINE else "amount"
        matches = [fact for fact in facts if fact.kind == wanted]
        if not matches:
            if wanted == "deadline" and _should_verify_portal(messages or []):
                portal_answer = _verify_deadline_from_portal(active_registry, tool_calls=tool_calls)
                if portal_answer is not None:
                    return portal_answer
            return AgentAnswer(
                intent=intent,
                answer="I cannot verify the latest fact from available email evidence.",
                confidence="uncertain",
                tool_calls=tuple(tool_calls),
                uncertain=True,
            )
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

    return AgentAnswer(
        intent=intent,
        answer="This question should use retrieval over trusted docs or local evidence before synthesis.",
        confidence="medium",
        tool_calls=(),
    )


def _should_verify_portal(messages: list[EmailMessage]) -> bool:
    terms = ("log in", "login", "sign in", "portal", "view online", "view your account", "account center")
    for message in messages:
        text = " ".join([message.subject, message.body_text, *message.attachment_texts]).lower()
        if any(term in text for term in terms):
            return True
    return False


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


def _answer_policy_question(active_registry: ToolRegistry, question: str) -> AgentAnswer:
    try:
        spec = active_registry.assert_can_call("search_policy_docs")
    except (KeyError, PermissionError) as error:
        return AgentAnswer(
            intent=Intent.POLICY_QUESTION,
            answer=f"I cannot search local policy documents for this question: {type(error).__name__}: {error}",
            confidence="uncertain",
            tool_calls=("search_policy_docs",),
            uncertain=True,
        )
    if spec.handler is None:
        return AgentAnswer(
            intent=Intent.POLICY_QUESTION,
            answer="I need a configured local RAG index to answer this policy question with citations.",
            confidence="uncertain",
            tool_calls=("search_policy_docs",),
            uncertain=True,
        )
    try:
        result = active_registry.call("search_policy_docs", query=question, limit=3)
    except Exception as error:
        return AgentAnswer(
            intent=Intent.POLICY_QUESTION,
            answer=f"I could not search the local RAG index: {type(error).__name__}: {error}",
            confidence="uncertain",
            tool_calls=("search_policy_docs",),
            uncertain=True,
        )
    documents = list(result.get("documents") or []) if isinstance(result, dict) else []
    if not documents:
        return AgentAnswer(
            intent=Intent.POLICY_QUESTION,
            answer="I could not find a cited local policy document for this question.",
            confidence="uncertain",
            tool_calls=("search_policy_docs",),
            uncertain=True,
        )
    top = documents[0]
    metadata = dict(top.get("metadata") or {})
    title = str(metadata.get("title") or top.get("source_id") or "local policy document")
    warnings = list(top.get("warnings") or [])
    warning_text = " The retrieved text had prompt-injection warnings and was sanitized." if warnings else ""
    answer_text = _short_answer_from_doc(str(top.get("text") or ""))
    citations = tuple(
        Citation(
            source_id=str(document.get("source_id") or ""),
            source_type=str(document.get("source_type") or "local_doc"),
            evidence=str((document.get("metadata") or {}).get("document_source_id") or document.get("source_id") or ""),
            captured_at=str((document.get("metadata") or {}).get("indexed_at") or ""),
        )
        for document in documents
    )
    return AgentAnswer(
        intent=Intent.POLICY_QUESTION,
        answer=f"From {title}: {answer_text}{warning_text}",
        confidence="high" if str(top.get("trust_label") or "") in {"trusted_policy", "trusted_doc", "official_policy"} else "medium",
        citations=citations,
        tool_calls=("search_policy_docs",),
        metadata={
            "document_count": len(documents),
            "top_trust_label": str(top.get("trust_label") or ""),
            "top_score": metadata.get("score"),
            "warnings": warnings,
        },
    )


def _short_answer_from_doc(text: str, *, limit: int = 280) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


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


def _verify_deadline_from_portal(active_registry: ToolRegistry, *, tool_calls: list[str]) -> AgentAnswer | None:
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
            tool_calls=tuple(portal_tool_calls),
            uncertain=True,
        )
    runs = list(result.get("runs") or []) if isinstance(result, dict) else []
    if not runs:
        return AgentAnswer(
            intent=Intent.LATEST_DEADLINE,
            answer="Email points to a portal, but no configured portal target ran.",
            confidence="uncertain",
            tool_calls=tuple(portal_tool_calls),
            uncertain=True,
        )
    latest = runs[0]
    deadlines = list(latest.get("deadlines") or [])
    if not deadlines:
        return AgentAnswer(
            intent=Intent.LATEST_DEADLINE,
            answer=f"Email points to a portal, but portal capture {latest.get('run_id')} did not expose a deadline.",
            confidence="uncertain",
            tool_calls=tuple(portal_tool_calls),
            uncertain=True,
            metadata={"run_id": str(latest.get("run_id") or "")},
        )
    deadline = deadlines[0]
    alert = latest.get("alert", {})
    evidence = latest.get("evidence", {})
    return AgentAnswer(
        intent=Intent.LATEST_DEADLINE,
        answer=f"Verified deadline from portal capture: {deadline.get('date_text')}",
        confidence="uncertain" if str(alert.get("level") or "") == "uncertain" else "medium",
        citations=(
            Citation(
                source_id=str(latest.get("run_id") or ""),
                source_type="portal_run",
                evidence=str(evidence.get("path") or ""),
                captured_at=str(latest.get("captured_at") or ""),
            ),
        ),
        tool_calls=tuple(portal_tool_calls),
        uncertain=str(alert.get("level") or "") == "uncertain",
        metadata={
            "run_id": str(latest.get("run_id") or ""),
            "fallback": "email_to_portal_deadline",
            "alert_level": str(alert.get("level") or ""),
        },
    )
