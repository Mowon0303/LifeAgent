from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from . import db
from .config import Paths
from .extract import utc_now


TASK_STATUSES = {"new", "reviewed", "ignored", "needs_verification", "done"}
TASK_KINDS = {"deadline", "amount", "action"}


@dataclass(frozen=True)
class TaskReviewResult:
    task_id: str
    status: str
    note: str
    actor: str
    updated_at: str
    task: dict[str, Any] | None


@dataclass(frozen=True)
class TaskBulkReviewResult:
    allowed: bool
    reason: str
    status: str
    actor: str
    updated_at: str
    confirmation_id: str
    filters: dict[str, Any]
    requested_count: int
    matched_count: int
    reviewed_count: int
    missing_task_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    tasks: tuple[dict[str, Any], ...]
    external_writes_performed: bool = False


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


def list_tasks(
    paths: Paths,
    *,
    status: str | None = None,
    kind: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    db.init_db(paths)
    reviews = {item["task_id"]: item for item in db.list_task_reviews(paths, limit=1000)}
    tasks = _calendar_tasks(paths, reviews)
    covered_source_ids = {
        source_id
        for task in tasks
        for source_id in task.get("source_refs", [])
        if source_id
    }
    tasks.extend(_email_fact_tasks(paths, reviews, covered_source_ids=covered_source_ids))
    tasks.sort(key=_task_sort_key)
    if status:
        _validate_status(status)
        tasks = [task for task in tasks if task.get("status") == status]
    if kind:
        _validate_kind(kind)
        tasks = [task for task in tasks if task.get("kind") == kind]
    return tasks[:limit]


def review_task(
    paths: Paths,
    *,
    task_id: str,
    status: str,
    note: str = "",
    actor: str = "user",
    updated_at: str | None = None,
) -> TaskReviewResult:
    db.init_db(paths)
    _validate_status(status)
    timestamp = updated_at or utc_now()
    db.upsert_task_review(
        paths,
        task_id=task_id,
        status=status,
        note=note,
        actor=actor,
        updated_at=timestamp,
    )
    task = get_task(paths, task_id)
    db.insert_audit_event(
        paths,
        action="task.review",
        actor=actor,
        subject=task_id,
        capability="task_review",
        side_effect="local_db_write",
        allowed=True,
        confirmation_id="",
        metadata={
            "status": status,
            "note_present": bool(note),
            "task_found": task is not None,
        },
        created_at=timestamp,
    )
    return TaskReviewResult(task_id=task_id, status=status, note=note, actor=actor, updated_at=timestamp, task=task)


def bulk_review_tasks(
    paths: Paths,
    *,
    status: str,
    task_ids: list[str] | tuple[str, ...] | None = None,
    kind: str | None = None,
    status_filter: str | None = None,
    limit: int = 100,
    note: str = "",
    actor: str = "user",
    confirmed: bool = False,
    confirmation_id: str = "",
    updated_at: str | None = None,
) -> TaskBulkReviewResult:
    db.init_db(paths)
    _validate_status(status)
    filters = _bulk_filters(kind=kind, status_filter=status_filter, limit=limit)
    requested_ids = tuple(str(task_id) for task_id in (task_ids or ()) if str(task_id))
    timestamp = updated_at or utc_now()
    selected = _bulk_selected_tasks(paths, task_ids=requested_ids, filters=filters)
    matched_ids = tuple(str(task.get("task_id") or "") for task in selected if task.get("task_id"))
    matched_set = set(matched_ids)
    missing_ids = tuple(task_id for task_id in requested_ids if task_id not in matched_set)
    requested_count = len(requested_ids) if requested_ids else len(selected)

    if not confirmed:
        reason = "confirmation_required"
        _audit_bulk_review(
            paths,
            action="task.review.bulk.blocked",
            actor=actor,
            allowed=False,
            confirmation_id=confirmation_id,
            timestamp=timestamp,
            metadata={
                "reason": reason,
                "target_status": status,
                "filters": filters,
                "requested_count": requested_count,
                "matched_count": len(selected),
                "missing_task_ids": list(missing_ids),
                "external_write": False,
            },
        )
        return TaskBulkReviewResult(
            allowed=False,
            reason=reason,
            status=status,
            actor=actor,
            updated_at=timestamp,
            confirmation_id=confirmation_id,
            filters=filters,
            requested_count=requested_count,
            matched_count=len(selected),
            reviewed_count=0,
            missing_task_ids=missing_ids,
            task_ids=matched_ids,
            tasks=tuple(selected),
        )

    if not confirmation_id:
        raise ValueError("confirmation_id required for bulk task review")
    if db.approval_record_exists(
        paths,
        confirmation_id=confirmation_id,
        action="task.review.bulk",
        subject="filtered_task_queue",
    ):
        reason = "confirmation_id_already_consumed"
        _audit_bulk_review(
            paths,
            action="task.review.bulk.blocked",
            actor=actor,
            allowed=False,
            confirmation_id=confirmation_id,
            timestamp=timestamp,
            metadata={
                "reason": reason,
                "target_status": status,
                "filters": filters,
                "requested_count": requested_count,
                "matched_count": len(selected),
                "missing_task_ids": list(missing_ids),
                "external_write": False,
            },
        )
        return TaskBulkReviewResult(
            allowed=False,
            reason=reason,
            status=status,
            actor=actor,
            updated_at=timestamp,
            confirmation_id=confirmation_id,
            filters=filters,
            requested_count=requested_count,
            matched_count=len(selected),
            reviewed_count=0,
            missing_task_ids=missing_ids,
            task_ids=matched_ids,
            tasks=tuple(selected),
        )

    reviewed: list[dict[str, Any]] = []
    for task in selected:
        task_id = str(task.get("task_id") or "")
        if not task_id:
            continue
        result = review_task(
            paths,
            task_id=task_id,
            status=status,
            note=note,
            actor=actor,
            updated_at=timestamp,
        )
        if result.task:
            reviewed.append(result.task)

    db.insert_approval_record(
        paths,
        confirmation_id=confirmation_id,
        actor=actor,
        action="task.review.bulk",
        subject="filtered_task_queue",
        capability="task_review_bulk",
        side_effect="local_db_write",
        status="confirmed",
        evidence_refs=list(matched_ids),
        metadata={
            "target_status": status,
            "filters": filters,
            "requested_count": requested_count,
            "matched_count": len(selected),
            "reviewed_count": len(reviewed),
            "missing_task_ids": list(missing_ids),
            "external_write": False,
        },
        created_at=timestamp,
        consumed_at=timestamp,
    )
    _audit_bulk_review(
        paths,
        action="task.review.bulk",
        actor=actor,
        allowed=True,
        confirmation_id=confirmation_id,
        timestamp=timestamp,
        metadata={
            "target_status": status,
            "filters": filters,
            "requested_count": requested_count,
            "matched_count": len(selected),
            "reviewed_count": len(reviewed),
            "missing_task_ids": list(missing_ids),
            "external_write": False,
        },
    )
    return TaskBulkReviewResult(
        allowed=True,
        reason="confirmed",
        status=status,
        actor=actor,
        updated_at=timestamp,
        confirmation_id=confirmation_id,
        filters=filters,
        requested_count=requested_count,
        matched_count=len(selected),
        reviewed_count=len(reviewed),
        missing_task_ids=missing_ids,
        task_ids=matched_ids,
        tasks=tuple(reviewed),
    )


def get_task(paths: Paths, task_id: str) -> dict[str, Any] | None:
    for task in list_tasks(paths, limit=1000):
        if task.get("task_id") == task_id:
            return task
    return None


def _calendar_tasks(paths: Paths, reviews: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for row in db.list_calendar_drafts(paths, limit=1000):
        event_id = str(row.get("event_id") or "")
        if not event_id:
            continue
        task_id = f"calendar:{event_id}"
        review = reviews.get(task_id, {})
        source_refs = [str(item) for item in row.get("source_ids", []) if item]
        tasks.append(
            _apply_review(
                {
                    "task_id": task_id,
                    "kind": "deadline",
                    "title": str(row.get("title") or "Review deadline"),
                    "value": str(row.get("date_text") or ""),
                    "values": [str(row.get("date_text") or "")] if row.get("date_text") else [],
                    "fact_count": 1 if row.get("date_text") else 0,
                    "due_date": str(row.get("date_text") or ""),
                    "severity": str(row.get("severity") or "medium"),
                    "confidence": float(row.get("confidence") or 0.0),
                    "source_type": "calendar_draft",
                    "source_refs": source_refs,
                    "primary_source": source_refs[0] if source_refs else f"calendar:{event_id}",
                    "evidence": str(row.get("evidence_uri") or ""),
                    "calendar_event_id": event_id,
                    "sync_state": str(row.get("sync_state") or ""),
                    "created_at": str(row.get("created_at") or ""),
                    "updated_at": str(row.get("updated_at") or ""),
                    "needs_verification": _needs_verification(source_refs, str(row.get("confidence") or "")),
                },
                review,
            )
        )
    return tasks


def _email_fact_tasks(
    paths: Paths,
    reviews: dict[str, dict[str, Any]],
    *,
    covered_source_ids: set[str],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for fact in db.list_email_facts(paths, limit=1000):
        source_id = _fact_source_ref(fact)
        kind = str(fact.get("kind") or "")
        if kind == "deadline" and source_id in covered_source_ids:
            continue
        groups.setdefault((kind, source_id), []).append(fact)

    for (kind, source_id), facts in groups.items():
        primary = _primary_fact(facts)
        values = _fact_values(facts)
        value = values[0] if values else ""
        task_id = _email_task_id(kind=kind, source_id=source_id)
        review = reviews.get(task_id, {})
        tasks.append(
            _apply_review(
                {
                    "task_id": task_id,
                    "kind": kind,
                    "title": _email_task_title(primary, count=len(values)),
                    "value": value,
                    "values": values,
                    "fact_count": len(values),
                    "due_date": value if kind == "deadline" else "",
                    "severity": _severity_for_fact(kind),
                    "confidence": max(float(fact.get("confidence") or 0.0) for fact in facts),
                    "source_type": str(primary.get("source_type") or "email"),
                    "source_refs": [source_id] if source_id else [],
                    "primary_source": source_id,
                    "evidence": str(primary.get("evidence") or ""),
                    "calendar_event_id": "",
                    "sync_state": "",
                    "subject": str(primary.get("subject") or ""),
                    "sender": str(primary.get("sender") or ""),
                    "received_at": str(primary.get("message_received_at") or primary.get("received_at") or ""),
                    "updated_at": str(primary.get("message_received_at") or primary.get("received_at") or ""),
                    "needs_verification": any(
                        _needs_verification([source_id], str(fact.get("confidence") or "")) for fact in facts
                    ),
                },
                review,
            )
        )
    return tasks


def _apply_review(task: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    status = str(review.get("status") or "new")
    task["status"] = status
    task["review_note"] = str(review.get("note") or "")
    task["review_actor"] = str(review.get("actor") or "")
    task["reviewed_at"] = str(review.get("updated_at") or "")
    return task


def _primary_fact(facts: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        enumerate(facts),
        key=lambda item: (
            float(item[1].get("confidence") or 0.0),
            str(item[1].get("message_received_at") or item[1].get("received_at") or ""),
            -item[0],
        ),
    )[1]


def _fact_source_ref(fact: dict[str, Any]) -> str:
    source_id = str(fact.get("source_id") or "")
    if source_id:
        return source_id
    message_id = str(fact.get("message_id") or "")
    return f"email:{message_id}" if message_id else ""


def _fact_values(facts: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    ordered = sorted(
        enumerate(facts),
        key=lambda item: (
            str(item[1].get("message_received_at") or item[1].get("received_at") or ""),
            -item[0],
        ),
        reverse=True,
    )
    for _, fact in ordered:
        value = str(fact.get("value") or "")
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _email_task_id(*, kind: str, source_id: str) -> str:
    digest = hashlib.sha256("|".join(["email_fact_group", kind, source_id]).encode("utf-8")).hexdigest()[:16]
    return f"email:{digest}"


def _email_task_title(fact: dict[str, Any], *, count: int = 1) -> str:
    subject = str(fact.get("subject") or "email evidence")
    kind = str(fact.get("kind") or "fact").replace("_", " ")
    if count > 1:
        return f"Review {count} {kind} facts: {subject}"
    return f"Review {kind}: {subject}"


def _severity_for_fact(kind: str) -> str:
    if kind == "deadline":
        return "medium"
    if kind == "amount":
        return "medium"
    if kind == "action":
        return "medium"
    return "low"


def _needs_verification(source_refs: list[str], confidence: str) -> bool:
    if not source_refs:
        return True
    try:
        return float(confidence) < 0.7
    except ValueError:
        return False


def _task_sort_key(task: dict[str, Any]) -> tuple[str, str, str]:
    due_date = str(task.get("due_date") or "9999-99-99")
    updated_at = str(task.get("updated_at") or task.get("received_at") or "")
    return (due_date, str(task.get("status") or ""), updated_at)


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
        "confidence": float(fact.get("confidence") or 0.0),
        "evidence": _clip(str(fact.get("evidence") or ""), 500),
        "source_id": str(fact.get("source_id") or ""),
        "source_type": str(fact.get("source_type") or ""),
        "received_at": str(fact.get("received_at") or ""),
    }


def _message_id_from_source_ref(source_ref: str) -> str:
    if ":" not in source_ref:
        return source_ref
    return source_ref.split(":", 1)[1]


def _clip(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "..."


def _validate_status(status: str) -> None:
    if status not in TASK_STATUSES:
        allowed = ", ".join(sorted(TASK_STATUSES))
        raise ValueError(f"Unsupported task status: {status}. Expected one of: {allowed}")


def _validate_kind(kind: str) -> None:
    if kind not in TASK_KINDS:
        allowed = ", ".join(sorted(TASK_KINDS))
        raise ValueError(f"Unsupported task kind: {kind}. Expected one of: {allowed}")


def _bulk_filters(*, kind: str | None, status_filter: str | None, limit: int) -> dict[str, Any]:
    normalized_kind = str(kind or "all")
    normalized_status = str(status_filter or "active")
    if normalized_kind != "all":
        _validate_kind(normalized_kind)
    if normalized_status not in {"active", "all"}:
        _validate_status(normalized_status)
    return {
        "kind": normalized_kind,
        "status": normalized_status,
        "limit": max(0, int(limit)),
    }


def _bulk_selected_tasks(
    paths: Paths,
    *,
    task_ids: tuple[str, ...],
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    all_tasks = list_tasks(paths, limit=1000)
    if task_ids:
        wanted = set(task_ids)
        return [task for task in all_tasks if str(task.get("task_id") or "") in wanted]
    kind = str(filters.get("kind") or "all")
    status_filter = str(filters.get("status") or "active")
    selected: list[dict[str, Any]] = []
    for task in all_tasks:
        if kind != "all" and task.get("kind") != kind:
            continue
        status = str(task.get("status") or "new")
        if status_filter == "active" and not _is_active_status(status):
            continue
        if status_filter not in {"active", "all"} and status != status_filter:
            continue
        selected.append(task)
    return selected[: int(filters.get("limit") or 0)]


def _is_active_status(status: str) -> bool:
    return status in {"new", "needs_verification", "reviewed"}


def _audit_bulk_review(
    paths: Paths,
    *,
    action: str,
    actor: str,
    allowed: bool,
    confirmation_id: str,
    timestamp: str,
    metadata: dict[str, Any],
) -> None:
    db.insert_audit_event(
        paths,
        action=action,
        actor=actor,
        subject="filtered_task_queue",
        capability="task_review_bulk",
        side_effect="local_db_write",
        allowed=allowed,
        confirmation_id=confirmation_id,
        metadata=metadata,
        created_at=timestamp,
    )
