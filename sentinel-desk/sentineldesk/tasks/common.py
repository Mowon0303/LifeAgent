"""Shared task constants, result dataclasses, and cross-cutting leaf helpers.

This is the leaf of the ``tasks`` package dependency graph: it imports nothing
from its siblings, so ``priority`` / ``listing`` / ``evidence`` / ``review`` /
``history`` can all depend on it without cycles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..calendar.view import parse_deadline_date


TASK_STATUSES = {"new", "reviewed", "ignored", "needs_verification", "done"}

# After a sender's mail has been ignored this many times, new items from it are
# auto-muted (sunk to the bottom) — the user's own ignore actions become the
# filter, instead of a hand-maintained block list.
MUTE_IGNORE_THRESHOLD = 3
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


def _confidence_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _task_due_key(task: dict[str, Any]) -> str:
    return parse_deadline_date(str(task.get("due_date") or task.get("value") or ""))


def _is_active_status(status: str) -> bool:
    return status in {"new", "needs_verification", "reviewed"}


def _has_payment_context(task: dict[str, Any]) -> bool:
    text = " ".join(
        str(task.get(key) or "")
        for key in ("title", "subject", "evidence", "due_date", "value")
    ).lower()
    return any(term in text for term in ("payment", "balance", "amount due", "minimum", "pay ", "due"))


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
