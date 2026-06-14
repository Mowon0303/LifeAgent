"""Task review layer: build the queue, score priority, expand evidence, and
record review / bulk-review / undo actions.

Historically a single ``tasks.py``; now a package split along a clean dependency
graph (common ← priority ← listing ← {evidence, review, history}). The public
call surface is preserved by re-exporting here, so callers keep writing
``from sentineldesk.tasks import list_tasks, review_task`` unchanged.
"""

from __future__ import annotations

from .common import (
    MUTE_IGNORE_THRESHOLD,
    TASK_KINDS,
    TASK_SORTS,
    TASK_STATUSES,
    TASK_VIEW_DEFAULT_SORT,
    TASK_VIEWS,
    TaskBulkReviewResult,
    TaskReviewResult,
    TaskReviewUndoResult,
)
from .priority import AMOUNT_RE
from .listing import get_task, list_tasks
from .evidence import calendar_event_evidence, task_evidence
from .review import bulk_review_tasks, review_task
from .history import (
    build_review_receipt_summary,
    list_review_history,
    undo_task_review,
)

__all__ = [
    # constants
    "TASK_STATUSES",
    "TASK_KINDS",
    "TASK_SORTS",
    "TASK_VIEWS",
    "TASK_VIEW_DEFAULT_SORT",
    "MUTE_IGNORE_THRESHOLD",
    "AMOUNT_RE",
    # result types
    "TaskReviewResult",
    "TaskBulkReviewResult",
    "TaskReviewUndoResult",
    # listing
    "list_tasks",
    "get_task",
    # evidence
    "task_evidence",
    "calendar_event_evidence",
    # review actions
    "review_task",
    "bulk_review_tasks",
    # history + undo
    "list_review_history",
    "build_review_receipt_summary",
    "undo_task_review",
]
