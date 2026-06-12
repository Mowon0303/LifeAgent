from __future__ import annotations

from collections import Counter
from typing import Any

from . import db
from .calendar.view import build_calendar_items
from .config import Paths
from .extract import utc_now
from .tasks import build_review_receipt_summary, list_tasks


LANDING_STATUSES = {"new", "needs_verification", "reviewed"}


def build_daily_landing_summary(
    paths: Paths,
    *,
    sync_summary: dict[str, Any] | None = None,
    task_limit: int = 12,
    calendar_limit: int = 20,
    actor: str = "system",
    now: str | None = None,
    record_audit: bool = True,
) -> dict[str, Any]:
    """Build the repeatable local daily workflow summary.

    This function intentionally does not perform external writes. Optional mail
    refresh happens before this function and is passed in as `sync_summary`.
    """
    db.init_db(paths)
    timestamp = now or utc_now()
    messages = db.list_email_messages(paths, limit=500)
    facts = db.list_email_facts(paths, limit=1000)
    all_tasks = list_tasks(paths, limit=1000)
    task_queue = [task for task in all_tasks if str(task.get("status") or "new") in LANDING_STATUSES]
    task_queue.sort(key=_landing_task_sort_key)
    approvals = db.list_approval_records(paths, limit=500)
    calendar_items = build_calendar_items(db.list_calendar_drafts(paths, limit=1000), approvals)
    visible_calendar = calendar_items[:calendar_limit]

    task_counts = Counter(str(task.get("status") or "new") for task in all_tasks)
    fact_counts = Counter(str(fact.get("kind") or "unknown") for fact in facts)
    connector_states = [_safe_connector_state(state) for state in db.list_connector_states(paths, limit=20)]
    pending_calendar = [item for item in calendar_items if item.get("approval_state") == "draft"]
    uncertain_calendar = [item for item in calendar_items if item.get("uncertain")]

    summary = {
        "status": "ready",
        "generated_at": timestamp,
        "mode": "daily_landing",
        "sync": _safe_sync_summary(sync_summary)
        if sync_summary
        else {
            "mode": "stored_only",
            "external_network": False,
            "messages_persisted": 0,
            "facts_extracted": 0,
            "deadline_events_drafted": 0,
        },
        "email": {
            "stored_message_count": len(messages),
            "latest_received_at": max((str(message.get("received_at") or "") for message in messages), default=""),
            "fact_counts": dict(sorted(fact_counts.items())),
        },
        "tasks": {
            "total": len(all_tasks),
            "counts_by_status": dict(sorted(task_counts.items())),
            "queue_count": len(task_queue),
            "queue": task_queue[:task_limit],
        },
        "calendar": {
            "total_drafts": len(calendar_items),
            "pending_count": len(pending_calendar),
            "uncertain_count": len(uncertain_calendar),
            "items": visible_calendar,
        },
        "connectors": connector_states,
        "review_receipt": build_review_receipt_summary(paths, limit=50, recent_limit=5),
        "safety": {
            "external_writes_performed": False,
            "calendar_writes_require_confirmation": True,
            "gmail_scope": "readonly",
            "raw_secret_values_included": False,
            "local_audit_written": record_audit,
        },
        "next_actions": _next_actions(task_queue=task_queue, pending_calendar=pending_calendar, sync_summary=sync_summary),
    }
    if record_audit:
        db.insert_audit_event(
            paths,
            action="daily.run",
            actor=actor,
            subject="daily_landing",
            capability="daily_workflow",
            side_effect="local_db_write",
            allowed=True,
            confirmation_id="",
            metadata={
                "stored_message_count": summary["email"]["stored_message_count"],
                "task_queue_count": summary["tasks"]["queue_count"],
                "calendar_pending_count": summary["calendar"]["pending_count"],
                "sync_mode": summary["sync"].get("mode", ""),
                "external_writes_performed": False,
            },
            created_at=timestamp,
        )
    return summary


def _safe_sync_summary(sync_summary: dict[str, Any]) -> dict[str, Any]:
    safe = dict(sync_summary)
    if safe.get("account_id"):
        safe["account_id"] = "[REDACTED_CONNECTOR_METADATA]"
    if safe.get("cursor"):
        safe["cursor"] = "[REDACTED_CONNECTOR_METADATA]"
    return safe


def _landing_task_sort_key(task: dict[str, Any]) -> tuple[int, str, str, str]:
    status = str(task.get("status") or "new")
    status_rank = {"needs_verification": 0, "new": 1, "reviewed": 2}.get(status, 3)
    due_date = str(task.get("due_date") or "9999-99-99")
    priority = int(task.get("priority_score") or 0)
    return (-priority, status_rank, due_date, str(task.get("task_id") or ""))


def _safe_connector_state(state: dict[str, Any]) -> dict[str, Any]:
    metadata = state.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "connector": str(state.get("connector") or ""),
        "account_id": "[REDACTED_CONNECTOR_METADATA]" if state.get("account_id") else "",
        "has_cursor": bool(state.get("cursor")),
        "scopes": list(state.get("scopes") or []),
        "updated_at": str(state.get("updated_at") or ""),
        "source_type": str(metadata.get("source_type") or ""),
        "trust_label": str(metadata.get("trust_label") or ""),
    }


def _next_actions(
    *,
    task_queue: list[dict[str, Any]],
    pending_calendar: list[dict[str, Any]],
    sync_summary: dict[str, Any] | None,
) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    if sync_summary is None:
        actions.append(
            {
                "kind": "refresh",
                "label": "Refresh inbox evidence",
                "command": "sentineldesk daily run --sync-gmail --account <account>",
                "side_effect": "gmail_readonly_plus_local_db_write",
            }
        )
    if task_queue:
        actions.append(
            {
                "kind": "review_tasks",
                "label": "Review extracted tasks",
                "command": "sentineldesk tasks list --view all --sort priority --status new",
                "side_effect": "local_read",
            }
        )
    if pending_calendar:
        actions.append(
            {
                "kind": "review_calendar",
                "label": "Review local calendar drafts before any sync",
                "command": "sentineldesk calendar sync --destination ics",
                "side_effect": "preview_only_without_confirm",
            }
        )
    actions.append(
        {
            "kind": "ask",
            "label": "Ask a tool-verified follow-up question",
            "command": 'sentineldesk ask "what should I do next?"',
            "side_effect": "local_read",
        }
    )
    return actions
