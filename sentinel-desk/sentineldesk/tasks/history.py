"""Review history, receipt summaries, and confirmation-gated undo."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .. import db
from ..config import Paths
from ..extract import utc_now
from .common import TaskReviewUndoResult, _validate_status
from .listing import get_task


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
