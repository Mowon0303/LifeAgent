"""Single and confirmation-gated bulk review actions over the task queue."""

from __future__ import annotations

from typing import Any

from .. import db
from ..config import Paths
from ..extract import utc_now
from .common import (
    TaskBulkReviewResult,
    TaskReviewResult,
    _is_active_status,
    _validate_kind,
    _validate_status,
)
from .listing import get_task, list_tasks


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
