"""Local source-evidence views for tasks and calendar drafts (no external reads)."""

from __future__ import annotations

from typing import Any

from .. import db
from ..calendar.view import parse_deadline_date
from ..config import Paths
from .common import _confidence_value
from .listing import get_task


def task_evidence(paths: Paths, *, task_id: str) -> dict[str, Any]:
    """Return local source evidence for a task without external reads."""
    db.init_db(paths)
    task = get_task(paths, task_id)
    if not task:
        raise ValueError(f"Task not found: {task_id}")
    sources = [_task_source_detail(task, message) for message in _source_messages(paths, task)]
    return {
        "task_id": task_id,
        "task": task,
        "sources": sources,
        "source_count": len(sources),
        "external_network": False,
        "external_writes_performed": False,
    }


def calendar_event_evidence(paths: Paths, *, event_id: str) -> dict[str, Any]:
    """Return local email evidence behind a calendar draft without external reads."""
    db.init_db(paths)
    event = next(
        (item for item in db.list_calendar_drafts(paths, limit=1000) if str(item.get("event_id") or "") == event_id),
        None,
    )
    if not event:
        raise ValueError(f"Calendar event not found: {event_id}")

    source_ids = [str(source_id) for source_id in event.get("source_ids", []) if str(source_id)]
    source_variants = {variant for source_id in source_ids for variant in _source_id_variants(source_id)}
    sources: list[dict[str, Any]] = []
    for message in db.list_email_messages(paths, limit=5000):
        message_variants = _source_id_variants(str(message.get("message_id") or ""))
        if not source_variants.intersection(message_variants):
            continue
        sources.append(_calendar_source_detail(event, message, source_variants))

    return {
        "event_id": event_id,
        "event": event,
        "sources": sources,
        "source_count": len(sources),
        "external_network": False,
        "external_writes_performed": False,
    }


def _source_messages(paths: Paths, task: dict[str, Any]) -> list[dict[str, Any]]:
    source_refs = {str(item) for item in task.get("source_refs", []) if item}
    message_ids = {_message_id_from_source_ref(source_ref) for source_ref in source_refs}
    message_ids.discard("")
    matched: list[dict[str, Any]] = []
    for message in db.list_email_messages(paths, limit=1000):
        facts = [fact for fact in message.get("facts", []) if isinstance(fact, dict)]
        if str(message.get("message_id") or "") in message_ids:
            matched.append(message)
            continue
        if any(str(fact.get("source_id") or "") in source_refs for fact in facts):
            matched.append(message)
    return matched


def _task_source_detail(task: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
    kind = str(task.get("kind") or "")
    source_refs_list = [str(item) for item in task.get("source_refs", []) if item]
    source_refs = set(source_refs_list)
    message_id = str(message.get("message_id") or "")
    attachment_names = [str(item) for item in message.get("attachment_names", [])]
    attachment_texts = list(message.get("attachment_texts", []) or [])
    facts = [
        _evidence_fact(fact)
        for fact in message.get("facts", [])
        if isinstance(fact, dict) and _fact_matches_task(fact, kind=kind, source_refs=source_refs, message_id=message_id)
    ]
    return {
        "source_id": str(task.get("primary_source") or (source_refs_list[0] if source_refs_list else "")),
        "message_id": message_id,
        "thread_id": str(message.get("thread_id") or ""),
        "sender": str(message.get("sender") or ""),
        "subject": str(message.get("subject") or ""),
        "received_at": str(message.get("received_at") or ""),
        "body_preview": _clip(str(message.get("body_text") or ""), 1200),
        "attachment_names": attachment_names,
        "attachment_count": max(len(attachment_names), len(attachment_texts)),
        "matched_facts": facts,
        "fact_count": len(facts),
    }


def _calendar_source_detail(
    event: dict[str, Any],
    message: dict[str, Any],
    source_variants: set[str],
) -> dict[str, Any]:
    message_id = str(message.get("message_id") or "")
    attachment_names = [str(item) for item in message.get("attachment_names", [])]
    attachment_texts = list(message.get("attachment_texts", []) or [])
    facts = [
        _evidence_fact(fact)
        for fact in message.get("facts", [])
        if isinstance(fact, dict) and _fact_matches_calendar_event(fact, event=event, source_variants=source_variants)
    ]
    if not facts:
        facts = [
            _evidence_fact(fact)
            for fact in message.get("facts", [])
            if isinstance(fact, dict) and _source_id_variants(str(fact.get("source_id") or "")).intersection(source_variants)
        ]
    facts = _dedupe_evidence_facts(facts)
    facts.sort(key=lambda fact: _calendar_fact_sort_key(fact, event=event))
    return {
        "source_id": str((event.get("source_ids") or [""])[0] or ""),
        "message_id": message_id,
        "thread_id": str(message.get("thread_id") or ""),
        "sender": str(message.get("sender") or ""),
        "subject": str(message.get("subject") or ""),
        "received_at": str(message.get("received_at") or ""),
        "body_preview": _clip(str(message.get("body_text") or ""), 5000),
        "attachment_names": attachment_names,
        "attachment_count": max(len(attachment_names), len(attachment_texts)),
        "matched_facts": facts,
        "fact_count": len(facts),
    }


def _fact_matches_calendar_event(fact: dict[str, Any], *, event: dict[str, Any], source_variants: set[str]) -> bool:
    if str(fact.get("kind") or "") != "deadline":
        return False
    if not _source_id_variants(str(fact.get("source_id") or "")).intersection(source_variants):
        return False
    event_date = str(event.get("date_text") or event.get("date_key") or "").strip().lower()
    value = str(fact.get("value") or "").strip().lower()
    event_date_key = parse_deadline_date(event_date) or str(event.get("date_key") or "").strip().lower()
    value_date_key = parse_deadline_date(value)
    if event_date_key and value_date_key and event_date_key == value_date_key:
        return True
    if event_date and value and (event_date == value or value in event_date or event_date in value):
        return True
    return False


def _calendar_fact_sort_key(fact: dict[str, Any], *, event: dict[str, Any]) -> tuple[int, float, str]:
    event_date = str(event.get("date_text") or event.get("date_key") or "").strip().lower()
    value = str(fact.get("value") or "").strip().lower()
    evidence = str(fact.get("evidence") or "").strip().lower()
    event_date_key = parse_deadline_date(event_date) or str(event.get("date_key") or "").strip().lower()
    value_date_key = parse_deadline_date(value)
    exact = bool(
        (event_date_key and value_date_key and event_date_key == value_date_key)
        or (event_date and (event_date == value or event_date in value or event_date in evidence))
    )
    return (0 if exact else 1, -_confidence_value(fact.get("confidence")), value)


def _fact_matches_task(fact: dict[str, Any], *, kind: str, source_refs: set[str], message_id: str) -> bool:
    if kind and str(fact.get("kind") or "") != kind:
        return False
    fact_source = str(fact.get("source_id") or "")
    if fact_source in source_refs:
        return True
    return bool(message_id and any(_message_id_from_source_ref(source_ref) == message_id for source_ref in source_refs))


def _evidence_fact(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": str(fact.get("kind") or ""),
        "value": str(fact.get("value") or ""),
        "confidence": _confidence_value(fact.get("confidence")),
        "evidence": _clip(str(fact.get("evidence") or ""), 1000),
        "source_id": str(fact.get("source_id") or ""),
        "source_type": str(fact.get("source_type") or ""),
        "received_at": str(fact.get("received_at") or ""),
    }


def _dedupe_evidence_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for fact in facts:
        value = str(fact.get("value") or "")
        key = (
            str(fact.get("kind") or ""),
            parse_deadline_date(value) or " ".join(value.lower().split()),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(fact)
    return deduped


def _message_id_from_source_ref(source_ref: str) -> str:
    if ":" not in source_ref:
        return source_ref
    return source_ref.split(":", 1)[1]


def _source_id_variants(source_id: str) -> set[str]:
    source_id = str(source_id or "").strip()
    if not source_id:
        return set()
    bare = _message_id_from_source_ref(source_id)
    return {source_id, bare, f"email:{bare}", f"gmail:{bare}"}


def _clip(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "..."
