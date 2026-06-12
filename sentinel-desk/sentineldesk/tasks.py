from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from . import db
from .config import Paths
from .extract import utc_now


TASK_STATUSES = {"new", "reviewed", "ignored", "needs_verification", "done"}


@dataclass(frozen=True)
class TaskReviewResult:
    task_id: str
    status: str
    note: str
    actor: str
    updated_at: str
    task: dict[str, Any] | None


def list_tasks(paths: Paths, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
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


def _validate_status(status: str) -> None:
    if status not in TASK_STATUSES:
        allowed = ", ".join(sorted(TASK_STATUSES))
        raise ValueError(f"Unsupported task status: {status}. Expected one of: {allowed}")
