"""Route handlers for the task review queue, evidence, history, and undo."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from ..tasks import (
    build_review_receipt_summary,
    bulk_review_tasks,
    list_review_history,
    list_tasks,
    review_task,
    task_evidence,
    undo_task_review,
)
from .helpers import body_int, query_int, truthy

if TYPE_CHECKING:  # pragma: no cover - typing only
    from urllib.parse import ParseResult

    from .app import Handler


def handle_tasks(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    try:
        h.send_json(
            list_tasks(
                h.paths,
                status=query.get("status", [None])[0],
                kind=query.get("kind", [None])[0],
                sort=query.get("sort", [None])[0],
                view=query.get("view", ["all"])[0],
                limit=query_int(query, "limit", 100),
            )
        )
    except ValueError as error:
        h.send_json({"error": str(error)}, status=400)


def handle_tasks_review_history(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    h.send_json(
        {
            "history": list_review_history(h.paths, limit=query_int(query, "limit", 20), include_calendar=True),
            "external_network": False,
            "external_writes_performed": False,
        }
    )


def handle_tasks_review_summary(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    h.send_json(
        build_review_receipt_summary(
            h.paths,
            limit=query_int(query, "limit", 50),
            recent_limit=query_int(query, "recent_limit", 5),
        )
    )


def handle_tasks_evidence(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    task_id = query.get("task_id", [""])[0]
    if not task_id:
        h.send_json({"error": "task_id query parameter required"}, status=400)
        return
    try:
        h.send_json(task_evidence(h.paths, task_id=task_id))
    except ValueError as error:
        h.send_json({"error": str(error)}, status=404)


def handle_tasks_review_bulk(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    body = h.read_json_body()
    task_ids = body.get("task_ids") if isinstance(body.get("task_ids"), list) else query.get("task_id", [])
    task_ids = [str(task_id) for task_id in task_ids if str(task_id)]
    filter_payload = body.get("filter") if isinstance(body.get("filter"), dict) else {}
    status = str(body.get("status") or query.get("status", [""])[0])
    if not status:
        h.send_json({"error": "status field required"}, status=400)
        return
    try:
        result = bulk_review_tasks(
            h.paths,
            task_ids=task_ids,
            status=status,
            kind=str(filter_payload.get("kind") or query.get("kind", ["all"])[0]),
            status_filter=str(filter_payload.get("status") or query.get("filter_status", ["active"])[0]),
            limit=query_int(query, "limit", body_int(body, "limit", 100)),
            note=str(body.get("note") or query.get("note", [""])[0]),
            actor="dashboard",
            confirmed=truthy(body.get("confirm", query.get("confirm", ["0"])[0])),
            confirmation_id=str(body.get("confirmation_id") or query.get("confirmation_id", [""])[0]),
        )
        h.send_json(result.__dict__)
    except ValueError as error:
        h.send_json({"error": str(error)}, status=400)
    except Exception as error:  # noqa: BLE001 - fail-soft API surface
        h.send_json({"error": str(error)}, status=500)


def handle_tasks_review_undo(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    body = h.read_json_body()
    audit_id_raw = body.get("audit_id") or query.get("audit_id", [""])[0]
    if not audit_id_raw:
        h.send_json({"error": "audit_id field required"}, status=400)
        return
    try:
        result = undo_task_review(
            h.paths,
            audit_id=int(audit_id_raw),
            actor="dashboard",
            confirmed=truthy(body.get("confirm", query.get("confirm", ["0"])[0])),
            confirmation_id=str(body.get("confirmation_id") or query.get("confirmation_id", [""])[0]),
        )
        h.send_json(result.__dict__)
    except ValueError as error:
        h.send_json({"error": str(error)}, status=400)
    except Exception as error:  # noqa: BLE001 - fail-soft API surface
        h.send_json({"error": str(error)}, status=500)


def handle_tasks_review(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    # Accept one or several task_id params: the dashboard groups a source email's
    # facts into a single card, so "完成" resolves every fact of that email in one
    # call. A single task_id (the common case, and the calendar-draft path) is
    # just a list of one — the response keeps its original single-task shape.
    task_ids = [task_id for task_id in query.get("task_id", []) if task_id]
    status = query.get("status", [""])[0]
    if not task_ids:
        h.send_json({"error": "task_id query parameter required"}, status=400)
        return
    if not status:
        h.send_json({"error": "status query parameter required"}, status=400)
        return
    try:
        note = query.get("note", [""])[0]
        results = [
            review_task(h.paths, task_id=task_id, status=status, note=note, actor="dashboard")
            for task_id in task_ids
        ]
        primary = results[0]
        h.send_json(
            {
                "task_id": primary.task_id,
                "task_ids": [result.task_id for result in results],
                "reviewed_count": len(results),
                "status": primary.status,
                "note": primary.note,
                "actor": primary.actor,
                "updated_at": primary.updated_at,
                "task": primary.task,
            }
        )
    except ValueError as error:
        h.send_json({"error": str(error)}, status=400)
    except Exception as error:  # noqa: BLE001 - fail-soft API surface
        h.send_json({"error": str(error)}, status=500)
