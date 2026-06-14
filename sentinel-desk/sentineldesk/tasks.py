from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from . import db
from .calendar.view import parse_deadline_date
from .config import Paths
from .extract import utc_now


TASK_STATUSES = {"new", "reviewed", "ignored", "needs_verification", "done"}
TASK_KINDS = {"deadline", "amount", "action"}
TASK_SORTS = {"priority", "due_date", "recent"}
TASK_VIEWS = {"all", "needs_verification", "payments", "deadlines_soon", "recently_changed"}
TASK_VIEW_DEFAULT_SORT = {
    "all": "priority",
    "needs_verification": "priority",
    "payments": "priority",
    "deadlines_soon": "due_date",
    "recently_changed": "recent",
}
AMOUNT_RE = re.compile(r"[$\u20ac\u00a3\u00a5\uffe5]?\s*(\d[\d,]*(?:\.\d{1,2})?)")


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


@dataclass(frozen=True)
class TaskReviewUndoResult:
    allowed: bool
    reason: str
    audit_id: int
    actor: str
    updated_at: str
    confirmation_id: str
    restored_count: int
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


def list_tasks(
    paths: Paths,
    *,
    status: str | None = None,
    kind: str | None = None,
    sort: str | None = None,
    view: str = "all",
    limit: int = 100,
    today: str | None = None,
) -> list[dict[str, Any]]:
    db.init_db(paths)
    _validate_view(view)
    sort = sort or TASK_VIEW_DEFAULT_SORT[view]
    _validate_sort(sort)
    today_key = (today or utc_now())[:10]
    reviews = {item["task_id"]: item for item in db.list_task_reviews(paths, limit=1000)}
    tasks = _calendar_tasks(paths, reviews)
    covered_source_ids = {
        source_id
        for task in tasks
        for source_id in task.get("source_refs", [])
        if source_id
    }
    tasks.extend(_email_fact_tasks(paths, reviews, covered_source_ids=covered_source_ids))
    # A deadline whose date is already past is not actionable, so drop it from
    # the review queue (dateless / relative deadlines have no due_key and stay).
    tasks = [task for task in tasks if not _deadline_is_past(task, today_key)]
    for task in tasks:
        _apply_priority(task)
    tasks = _apply_view(tasks, view=view)
    tasks.sort(key=lambda task: _task_sort_key(task, sort=sort))
    if status:
        _validate_status(status)
        tasks = [task for task in tasks if task.get("status") == status]
    if kind:
        _validate_kind(kind)
        tasks = [task for task in tasks if task.get("kind") == kind]
    return tasks[:limit]


def _unconfirmed_event_ids(events: list[dict[str, Any]]) -> set[str]:
    """Calendar draft event ids that were later reverted via /api/calendar/unconfirm."""
    reverted: set[str] = set()
    for event in events:
        if str(event.get("action") or "") != "calendar.unsync" or not event.get("allowed"):
            continue
        subject = str(event.get("subject") or "")
        if subject:
            reverted.add(subject)
    return reverted


def list_review_history(paths: Paths, *, limit: int = 20, include_calendar: bool = False) -> list[dict[str, Any]]:
    db.init_db(paths)
    limit = max(0, int(limit))
    if limit == 0:
        return []
    history_limit = max(limit * 10, 100)
    events = db.list_audit_events(paths, limit=history_limit)
    undone_ids = _undone_source_audit_ids(events)
    reverted_event_ids = _unconfirmed_event_ids(events) if include_calendar else set()
    actions = {"task.review", "task.review.bulk"}
    if include_calendar:
        actions.add("calendar.sync")
    history: list[dict[str, Any]] = []
    for event in events:
        if str(event.get("action") or "") not in actions:
            continue
        history.append(_review_history_item(event, undone_ids=undone_ids, reverted_event_ids=reverted_event_ids))
        if len(history) >= limit:
            break
    return history


def build_review_receipt_summary(paths: Paths, *, limit: int = 50, recent_limit: int = 5) -> dict[str, Any]:
    """Summarize local task review history without external reads or writes."""
    db.init_db(paths)
    limit = max(0, int(limit))
    recent_limit = max(0, int(recent_limit))
    history = list_review_history(paths, limit=limit)
    effective = [item for item in history if item.get("undo_status") != "undone"]
    counts_by_status: Counter[str] = Counter()
    counts_by_action: Counter[str] = Counter()
    reviewed_task_count = 0
    net_changed_task_count = 0
    for item in history:
        count = int(item.get("reviewed_count") or 0)
        reviewed_task_count += count
        counts_by_action[str(item.get("action") or "unknown")] += 1
    for item in effective:
        count = int(item.get("reviewed_count") or 0)
        net_changed_task_count += count
        status = str(item.get("status") or "unknown")
        counts_by_status[status] += count
    return {
        "status": "ready",
        "generated_at": utc_now(),
        "mode": "local_review_receipt",
        "history_limit": limit,
        "review_event_count": len(history),
        "reviewed_task_count": reviewed_task_count,
        "net_changed_task_count": net_changed_task_count,
        "counts_by_status": dict(sorted(counts_by_status.items())),
        "counts_by_action": dict(sorted(counts_by_action.items())),
        "undoable_count": sum(1 for item in history if item.get("undoable")),
        "undone_count": sum(1 for item in history if item.get("undo_status") == "undone"),
        "latest_reviewed_at": str(history[0].get("created_at") or "") if history else "",
        "recent": history[:recent_limit],
        "external_network": False,
        "external_writes_performed": False,
    }


def undo_task_review(
    paths: Paths,
    *,
    audit_id: int,
    actor: str = "user",
    confirmed: bool = False,
    confirmation_id: str = "",
    updated_at: str | None = None,
) -> TaskReviewUndoResult:
    db.init_db(paths)
    timestamp = updated_at or utc_now()
    event = db.get_audit_event(paths, audit_id=int(audit_id))
    if not event:
        raise ValueError(f"Audit event not found: {audit_id}")
    action = str(event.get("action") or "")
    if action not in {"task.review", "task.review.bulk"}:
        raise ValueError(f"Audit event is not a task review event: {audit_id}")

    undo_items = tuple(_undo_items_from_event(event))
    task_ids = tuple(str(item.get("task_id") or "") for item in undo_items if item.get("task_id"))
    subject = f"audit:{int(audit_id)}"
    if not undo_items:
        reason = "not_undoable"
        _audit_review_undo(
            paths,
            action="task.review.undo.blocked",
            actor=actor,
            audit_id=int(audit_id),
            allowed=False,
            confirmation_id=confirmation_id,
            timestamp=timestamp,
            metadata={"reason": reason, "source_action": action, "external_write": False},
        )
        return TaskReviewUndoResult(
            allowed=False,
            reason=reason,
            audit_id=int(audit_id),
            actor=actor,
            updated_at=timestamp,
            confirmation_id=confirmation_id,
            restored_count=0,
            task_ids=task_ids,
            tasks=(),
        )

    if not confirmed:
        reason = "confirmation_required"
        _audit_review_undo(
            paths,
            action="task.review.undo.blocked",
            actor=actor,
            audit_id=int(audit_id),
            allowed=False,
            confirmation_id=confirmation_id,
            timestamp=timestamp,
            metadata={
                "reason": reason,
                "source_action": action,
                "task_ids": list(task_ids),
                "external_write": False,
            },
        )
        return TaskReviewUndoResult(
            allowed=False,
            reason=reason,
            audit_id=int(audit_id),
            actor=actor,
            updated_at=timestamp,
            confirmation_id=confirmation_id,
            restored_count=0,
            task_ids=task_ids,
            tasks=(),
        )

    if not confirmation_id:
        raise ValueError("confirmation_id required for task review undo")
    if db.approval_record_exists(
        paths,
        confirmation_id=confirmation_id,
        action="task.review.undo",
        subject=subject,
    ):
        reason = "confirmation_id_already_consumed"
        _audit_review_undo(
            paths,
            action="task.review.undo.blocked",
            actor=actor,
            audit_id=int(audit_id),
            allowed=False,
            confirmation_id=confirmation_id,
            timestamp=timestamp,
            metadata={
                "reason": reason,
                "source_action": action,
                "task_ids": list(task_ids),
                "external_write": False,
            },
        )
        return TaskReviewUndoResult(
            allowed=False,
            reason=reason,
            audit_id=int(audit_id),
            actor=actor,
            updated_at=timestamp,
            confirmation_id=confirmation_id,
            restored_count=0,
            task_ids=task_ids,
            tasks=(),
        )
    if _source_audit_already_undone(paths, audit_id=int(audit_id)):
        reason = "source_audit_already_undone"
        _audit_review_undo(
            paths,
            action="task.review.undo.blocked",
            actor=actor,
            audit_id=int(audit_id),
            allowed=False,
            confirmation_id=confirmation_id,
            timestamp=timestamp,
            metadata={
                "reason": reason,
                "source_action": action,
                "task_ids": list(task_ids),
                "external_write": False,
            },
        )
        return TaskReviewUndoResult(
            allowed=False,
            reason=reason,
            audit_id=int(audit_id),
            actor=actor,
            updated_at=timestamp,
            confirmation_id=confirmation_id,
            restored_count=0,
            task_ids=task_ids,
            tasks=(),
        )

    restored: list[dict[str, Any]] = []
    for item in undo_items:
        task = _restore_review_state(paths, item, actor=actor, timestamp=timestamp)
        if task:
            restored.append(task)

    db.insert_approval_record(
        paths,
        confirmation_id=confirmation_id,
        actor=actor,
        action="task.review.undo",
        subject=subject,
        capability="task_review_undo",
        side_effect="local_db_write",
        status="confirmed",
        evidence_refs=list(task_ids),
        metadata={
            "source_audit_id": int(audit_id),
            "source_action": action,
            "restored_count": len(restored),
            "task_ids": list(task_ids),
            "external_write": False,
        },
        created_at=timestamp,
        consumed_at=timestamp,
    )
    _audit_review_undo(
        paths,
        action="task.review.undo",
        actor=actor,
        audit_id=int(audit_id),
        allowed=True,
        confirmation_id=confirmation_id,
        timestamp=timestamp,
        metadata={
            "reason": "confirmed",
            "source_action": action,
            "restored_count": len(restored),
            "task_ids": list(task_ids),
            "external_write": False,
        },
    )
    return TaskReviewUndoResult(
        allowed=True,
        reason="confirmed",
        audit_id=int(audit_id),
        actor=actor,
        updated_at=timestamp,
        confirmation_id=confirmation_id,
        restored_count=len(restored),
        task_ids=task_ids,
        tasks=tuple(restored),
    )


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
    task_before = get_task(paths, task_id)
    undo_state = _review_undo_state(paths, task_id=task_id, task=task_before)
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
            "undoable": task_before is not None,
            "previous_status": undo_state["previous_status"],
            "previous_note": undo_state["previous_note"],
            "previous_actor": undo_state["previous_actor"],
            "previous_updated_at": undo_state["previous_updated_at"],
            "had_previous_review": undo_state["had_previous_review"],
            "external_write": False,
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
    undo_items = tuple(
        _review_undo_state(paths, task_id=str(task.get("task_id") or ""), task=task)
        for task in selected
        if task.get("task_id")
    )

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
            "task_ids": list(matched_ids),
            "undo_items": list(undo_items),
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
            "task_ids": list(matched_ids),
            "undo_items": list(undo_items),
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
                    "confidence": _confidence_value(row.get("confidence")),
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
                    "confidence": max(_confidence_value(fact.get("confidence")) for fact in facts),
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


def _apply_priority(task: dict[str, Any]) -> None:
    score = 0
    reasons: list[str] = []
    status = str(task.get("status") or "new")
    kind = str(task.get("kind") or "")
    severity = str(task.get("severity") or "medium")
    confidence = _confidence_value(task.get("confidence"))

    # A human-set "needs_verification" status is a real obligation signal (a
    # person flagged that work is owed). Automatic uncertainty is handled lower
    # down — as a reason only, never a score boost — so a low-confidence promo
    # cannot inflate itself into the high band.
    if status == "needs_verification":
        score += 100
        reasons.append("needs_verification_status")
    elif status == "new":
        score += 25
        reasons.append("new_item")
    elif status == "reviewed":
        score += 5
        reasons.append("already_reviewed")
    elif status in {"done", "ignored"}:
        reasons.append("closed")

    severity_score = {"critical": 75, "high": 60, "medium": 30, "low": 10}.get(severity, 20)
    score += severity_score
    reasons.append(f"{severity if severity in {'critical', 'high', 'medium', 'low'} else 'unknown'}_severity")

    if kind == "deadline":
        score += 35
        reasons.append("deadline")
    elif kind == "amount":
        score += 25
        reasons.append("amount")
    elif kind == "action":
        score += 20
        reasons.append("action")

    # Obligation signals — a concrete commitment, not "the extractor is unsure".
    # Only these (or a human needs_verification flag) earn the high band, so the
    # high lane is reserved for real dates and money owed rather than every
    # imperative verb the extractor caught in a newsletter.
    has_obligation = status == "needs_verification"
    due_key = _task_due_key(task)
    if kind == "deadline" and due_key:
        score += 15
        reasons.append("dated_deadline")
        has_obligation = True
    elif kind == "deadline" and task.get("due_date"):
        score += 10
        reasons.append("relative_or_unparsed_deadline")
        has_obligation = True

    if kind == "amount":
        amount = _max_amount(task)
        if amount >= 1000:
            score += 20
            reasons.append("large_amount")
            has_obligation = True
        elif amount >= 100:
            score += 10
            reasons.append("meaningful_amount")
            has_obligation = True
    if _has_payment_context(task):
        score += 15
        reasons.append("payment_context")
    if _has_action_context(task):
        score += 10
        reasons.append("action_context")

    # Uncertainty is recorded for the reviewer and the needs-verification view,
    # but it no longer raises priority: a low-confidence item should sink, not
    # surface. (Previously these two added +70 and pushed junk into "high".)
    if bool(task.get("needs_verification")):
        reasons.append("low_trust_or_missing_source")
    if confidence < 0.7:
        reasons.append("low_confidence")
    elif confidence < 0.8:
        reasons.append("medium_confidence")

    if status in {"done", "ignored"}:
        score = min(score, 20)
    task["priority_score"] = max(0, int(score))
    task["priority_band"] = _priority_band(task["priority_score"], status=status, has_obligation=has_obligation)
    task["priority_reasons"] = _unique_reasons(reasons)


def _priority_band(score: int, *, status: str, has_obligation: bool = False) -> str:
    if status in {"done", "ignored"}:
        return "closed"
    if has_obligation and score >= 100:
        return "high"
    if score >= 80:
        return "medium"
    return "low"


def _unique_reasons(reasons: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        if not reason or reason in seen:
            continue
        seen.add(reason)
        unique.append(reason)
    return unique


def _primary_fact(facts: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        enumerate(facts),
        key=lambda item: (
            _confidence_value(item[1].get("confidence")),
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
    return _confidence_value(confidence) < 0.7


def _confidence_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _task_sort_key(task: dict[str, Any], *, sort: str) -> tuple[Any, ...]:
    priority = int(task.get("priority_score") or 0)
    due_date = _task_due_key(task) or "9999-99-99"
    updated_at = _timestamp_value(
        str(task.get("updated_at") or task.get("received_at") or task.get("reviewed_at") or "")
    )
    status_rank = {"needs_verification": 0, "new": 1, "reviewed": 2, "done": 3, "ignored": 4}.get(
        str(task.get("status") or "new"),
        5,
    )
    task_id = str(task.get("task_id") or "")
    if sort == "priority":
        return (-priority, status_rank, due_date, -updated_at, task_id)
    if sort == "due_date":
        return (due_date, -priority, status_rank, -updated_at, task_id)
    if sort == "recent":
        return (-updated_at, -priority, status_rank, due_date, task_id)
    _validate_sort(sort)
    return (-priority, status_rank, due_date, -updated_at, task_id)


def _apply_view(tasks: list[dict[str, Any]], *, view: str) -> list[dict[str, Any]]:
    if view == "all":
        return tasks
    if view == "needs_verification":
        return [task for task in tasks if _is_verification_task(task)]
    if view == "payments":
        return [task for task in tasks if _is_payment_task(task)]
    if view == "deadlines_soon":
        return [task for task in tasks if str(task.get("kind") or "") == "deadline" and _task_due_key(task)]
    if view == "recently_changed":
        return [task for task in tasks if _task_has_timestamp(task) and _is_active_status(str(task.get("status") or "new"))]
    _validate_view(view)
    return tasks


def _is_verification_task(task: dict[str, Any]) -> bool:
    status = str(task.get("status") or "new")
    return (
        status == "needs_verification"
        or bool(task.get("needs_verification"))
        or _confidence_value(task.get("confidence")) < 0.7
        or "low_trust_or_missing_source" in set(task.get("priority_reasons") or [])
    )


def _is_payment_task(task: dict[str, Any]) -> bool:
    return (
        str(task.get("kind") or "") == "amount"
        or "payment_context" in set(task.get("priority_reasons") or [])
        or _has_payment_context(task)
    )


def _task_has_timestamp(task: dict[str, Any]) -> bool:
    return any(str(task.get(key) or "") for key in ("updated_at", "received_at", "reviewed_at", "created_at"))


def _task_due_key(task: dict[str, Any]) -> str:
    return parse_deadline_date(str(task.get("due_date") or task.get("value") or ""))


def _deadline_is_past(task: dict[str, Any], today_key: str) -> bool:
    if str(task.get("kind") or "") != "deadline":
        return False
    due_key = _task_due_key(task)
    return bool(due_key) and due_key < today_key


def _timestamp_value(value: str) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _max_amount(task: dict[str, Any]) -> float:
    values = task.get("values") if isinstance(task.get("values"), list) else []
    candidates = [str(value) for value in values]
    candidates.append(str(task.get("value") or ""))
    found: list[float] = []
    for candidate in candidates:
        for match in AMOUNT_RE.finditer(candidate):
            try:
                found.append(float(match.group(1).replace(",", "")))
            except ValueError:
                continue
    return max(found, default=0.0)


def _has_payment_context(task: dict[str, Any]) -> bool:
    text = " ".join(
        str(task.get(key) or "")
        for key in ("title", "subject", "evidence", "due_date", "value")
    ).lower()
    return any(term in text for term in ("payment", "balance", "amount due", "minimum", "pay ", "due"))


def _has_action_context(task: dict[str, Any]) -> bool:
    if str(task.get("kind") or "") != "action":
        return False
    text = " ".join(str(task.get(key) or "") for key in ("title", "subject", "evidence", "value")).lower()
    return any(
        term in text
        for term in (
            "submit",
            "schedule",
            "register",
            "apply",
            "verify",
            "reply",
            "contact",
            "cancel",
            "renew",
            "upload",
        )
    )


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


def _validate_status(status: str) -> None:
    if status not in TASK_STATUSES:
        allowed = ", ".join(sorted(TASK_STATUSES))
        raise ValueError(f"Unsupported task status: {status}. Expected one of: {allowed}")


def _validate_kind(kind: str) -> None:
    if kind not in TASK_KINDS:
        allowed = ", ".join(sorted(TASK_KINDS))
        raise ValueError(f"Unsupported task kind: {kind}. Expected one of: {allowed}")


def _validate_sort(sort: str) -> None:
    if sort not in TASK_SORTS:
        allowed = ", ".join(sorted(TASK_SORTS))
        raise ValueError(f"Unsupported task sort: {sort}. Expected one of: {allowed}")


def _validate_view(view: str) -> None:
    if view not in TASK_VIEWS:
        allowed = ", ".join(sorted(TASK_VIEWS))
        raise ValueError(f"Unsupported task view: {view}. Expected one of: {allowed}")


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


def _review_undo_state(paths: Paths, *, task_id: str, task: dict[str, Any] | None) -> dict[str, Any]:
    previous = db.get_task_review(paths, task_id=task_id)
    return {
        "task_id": task_id,
        "previous_status": str(previous.get("status") or "new") if previous else "new",
        "previous_note": str(previous.get("note") or "") if previous else "",
        "previous_actor": str(previous.get("actor") or "") if previous else "",
        "previous_updated_at": str(previous.get("updated_at") or "") if previous else "",
        "had_previous_review": previous is not None,
        "task_found": task is not None,
        "current_status": str(task.get("status") or "") if task else "",
    }


def _review_history_item(
    event: dict[str, Any], *, undone_ids: set[int], reverted_event_ids: set[str] | None = None
) -> dict[str, Any]:
    reverted_event_ids = reverted_event_ids or set()
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    action = str(event.get("action") or "")
    audit_id = int(event.get("id") or 0)
    kind = "task"
    event_id = ""
    if action == "calendar.sync":
        kind = "calendar"
        event_ids = [str(eid) for eid in (metadata.get("event_ids") or []) if str(eid)]
        event_id = event_ids[0] if event_ids else ""
        task_ids = event_ids
        reviewed_count = len(event_ids)
        status = "已加入日历"
        previous_status = "待确认"
        reverted = bool(event_id) and event_id in reverted_event_ids
        undoable = bool(event_id) and not reverted
        undo_status = "undone" if reverted else "available"
        summary = "加入日历（本地 ICS）"
        return {
            "audit_id": audit_id,
            "action": action,
            "kind": kind,
            "event_id": event_id,
            "actor": str(event.get("actor") or ""),
            "subject": str(event.get("subject") or ""),
            "created_at": str(event.get("created_at") or ""),
            "confirmation_id": str(event.get("confirmation_id") or ""),
            "status": status,
            "previous_status": previous_status,
            "reviewed_count": reviewed_count,
            "task_ids": task_ids,
            "undoable": undoable,
            "undo_status": undo_status,
            "summary": summary,
            "external_writes_performed": False,
        }
    if action == "task.review.bulk":
        undo_items = metadata.get("undo_items") if isinstance(metadata.get("undo_items"), list) else []
        task_ids = [str(item.get("task_id") or "") for item in undo_items if isinstance(item, dict)]
        if not task_ids and isinstance(metadata.get("task_ids"), list):
            task_ids = [str(task_id) for task_id in metadata["task_ids"] if str(task_id)]
        reviewed_count = int(metadata.get("reviewed_count") or len(task_ids))
        status = str(metadata.get("target_status") or "")
        previous_status = "mixed" if len({str(item.get("previous_status") or "") for item in undo_items if isinstance(item, dict)}) > 1 else (
            str(undo_items[0].get("previous_status") or "") if undo_items and isinstance(undo_items[0], dict) else ""
        )
        undoable = bool(undo_items) and audit_id not in undone_ids
        summary = f"Bulk marked {reviewed_count} task(s) as {status}"
    else:
        task_id = str(event.get("subject") or "")
        task_ids = [task_id] if task_id else []
        reviewed_count = 1 if task_id else 0
        status = str(metadata.get("status") or "")
        previous_status = str(metadata.get("previous_status") or "")
        undoable = bool(metadata.get("undoable") and previous_status and task_id) and audit_id not in undone_ids
        summary = f"Marked {task_id} as {status}" if task_id else f"Marked task as {status}"
    return {
        "audit_id": audit_id,
        "action": action,
        "kind": kind,
        "event_id": event_id,
        "actor": str(event.get("actor") or ""),
        "subject": str(event.get("subject") or ""),
        "created_at": str(event.get("created_at") or ""),
        "confirmation_id": str(event.get("confirmation_id") or ""),
        "status": status,
        "previous_status": previous_status,
        "reviewed_count": reviewed_count,
        "task_ids": task_ids,
        "undoable": undoable,
        "undo_status": "undone" if audit_id in undone_ids else "available",
        "summary": summary,
        "external_writes_performed": False,
    }


def _undo_items_from_event(event: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    action = str(event.get("action") or "")
    if action == "task.review.bulk":
        raw_items = metadata.get("undo_items")
        if not isinstance(raw_items, list):
            return []
        return [_normalize_undo_item(item) for item in raw_items if isinstance(item, dict) and item.get("task_id")]
    if action != "task.review" or not metadata.get("undoable"):
        return []
    task_id = str(event.get("subject") or "")
    if not task_id or "previous_status" not in metadata:
        return []
    return [
        _normalize_undo_item(
            {
                "task_id": task_id,
                "previous_status": metadata.get("previous_status"),
                "previous_note": metadata.get("previous_note"),
                "previous_actor": metadata.get("previous_actor"),
                "previous_updated_at": metadata.get("previous_updated_at"),
                "had_previous_review": metadata.get("had_previous_review"),
                "task_found": metadata.get("task_found"),
            }
        )
    ]


def _normalize_undo_item(item: dict[str, Any]) -> dict[str, Any]:
    status = str(item.get("previous_status") or "new")
    _validate_status(status)
    return {
        "task_id": str(item.get("task_id") or ""),
        "previous_status": status,
        "previous_note": str(item.get("previous_note") or ""),
        "previous_actor": str(item.get("previous_actor") or ""),
        "previous_updated_at": str(item.get("previous_updated_at") or ""),
        "had_previous_review": bool(item.get("had_previous_review")),
        "task_found": bool(item.get("task_found", True)),
    }


def _restore_review_state(paths: Paths, item: dict[str, Any], *, actor: str, timestamp: str) -> dict[str, Any] | None:
    task_id = str(item.get("task_id") or "")
    if not task_id:
        return None
    if item.get("had_previous_review"):
        db.upsert_task_review(
            paths,
            task_id=task_id,
            status=str(item.get("previous_status") or "new"),
            note=str(item.get("previous_note") or ""),
            actor=actor,
            updated_at=timestamp,
        )
    else:
        db.delete_task_review(paths, task_id=task_id)
    return get_task(paths, task_id)


def _undone_source_audit_ids(events: list[dict[str, Any]]) -> set[int]:
    undone: set[int] = set()
    for event in events:
        if str(event.get("action") or "") != "task.review.undo" or not event.get("allowed"):
            continue
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        try:
            undone.add(int(metadata.get("source_audit_id") or 0))
        except (TypeError, ValueError):
            continue
    undone.discard(0)
    return undone


def _source_audit_already_undone(paths: Paths, *, audit_id: int) -> bool:
    return audit_id in _undone_source_audit_ids(db.list_audit_events(paths, limit=1000))


def _audit_review_undo(
    paths: Paths,
    *,
    action: str,
    actor: str,
    audit_id: int,
    allowed: bool,
    confirmation_id: str,
    timestamp: str,
    metadata: dict[str, Any],
) -> None:
    merged = {
        "source_audit_id": audit_id,
        **metadata,
    }
    db.insert_audit_event(
        paths,
        action=action,
        actor=actor,
        subject=f"audit:{audit_id}",
        capability="task_review_undo",
        side_effect="local_db_write",
        allowed=allowed,
        confirmation_id=confirmation_id,
        metadata=merged,
        created_at=timestamp,
    )


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
