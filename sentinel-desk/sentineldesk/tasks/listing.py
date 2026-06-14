"""Build and order the task review queue from calendar drafts + email facts."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .. import db
from ..config import Paths
from ..extract import utc_now
from .common import (
    MUTE_IGNORE_THRESHOLD,
    TASK_VIEW_DEFAULT_SORT,
    _confidence_value,
    _has_payment_context,
    _is_active_status,
    _task_due_key,
    _validate_kind,
    _validate_sort,
    _validate_status,
    _validate_view,
)
from .priority import _apply_priority


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
    # Learn from the reviewer: senders whose mail has been ignored repeatedly get
    # their new items muted (sunk to "low"), so the user stops re-triaging the
    # same noise without ever writing a rule.
    muted_senders = _muted_senders(tasks)
    for task in tasks:
        is_muted = task.get("status") == "new" and _sender_key(str(task.get("sender") or "")) in muted_senders
        task["muted"] = is_muted
        if is_muted:
            task["priority_band"] = "low"
            if "muted_sender" not in task.get("priority_reasons", []):
                task["priority_reasons"] = [*task.get("priority_reasons", []), "muted_sender"]
    tasks = _apply_view(tasks, view=view)
    tasks.sort(key=lambda task: _task_sort_key(task, sort=sort))
    if status:
        _validate_status(status)
        tasks = [task for task in tasks if task.get("status") == status]
    if kind:
        _validate_kind(kind)
        tasks = [task for task in tasks if task.get("kind") == kind]
    return tasks[:limit]


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


def _deadline_is_past(task: dict[str, Any], today_key: str) -> bool:
    if str(task.get("kind") or "") != "deadline":
        return False
    due_key = _task_due_key(task)
    return bool(due_key) and due_key < today_key


def _sender_key(sender: str) -> str:
    """Normalize a 'Name <addr@host>' sender down to its lowercased address."""
    match = re.search(r"<([^>]+)>", sender)
    address = (match.group(1) if match else sender).strip().lower()
    return address if "@" in address else ""


def _muted_senders(tasks: list[dict[str, Any]]) -> set[str]:
    counts: Counter[str] = Counter()
    for task in tasks:
        if task.get("status") == "ignored":
            key = _sender_key(str(task.get("sender") or ""))
            if key:
                counts[key] += 1
    return {key for key, count in counts.items() if count >= MUTE_IGNORE_THRESHOLD}


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
