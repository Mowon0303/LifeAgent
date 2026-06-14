"""Route handlers for calendar drafts, events, evidence, and ICS sync."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from .. import db
from ..calendar.adapters import IcsFileCalendarAdapter, sync_calendar_draft
from ..calendar.models import CalendarDraft
from ..calendar.source import events_from_calendar_rows
from ..calendar.view import build_calendar_items
from ..extract import utc_now
from ..tasks import calendar_event_evidence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from urllib.parse import ParseResult

    from .app import Handler


def handle_calendar_drafts(h: "Handler", parsed: "ParseResult") -> None:
    h.send_json(db.list_calendar_drafts(h.paths, limit=100))


def handle_calendar_events(h: "Handler", parsed: "ParseResult") -> None:
    h.send_json(
        build_calendar_items(
            db.list_calendar_drafts(h.paths, limit=200),
            db.list_approval_records(h.paths, limit=200),
        )
    )


def handle_calendar_evidence(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    event_id = query.get("event_id", [""])[0]
    if not event_id:
        h.send_json({"error": "event_id query parameter required"}, status=400)
        return
    try:
        h.send_json(calendar_event_evidence(h.paths, event_id=event_id))
    except ValueError as error:
        h.send_json({"error": str(error)}, status=404)


def handle_calendar_sync(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    confirmed = query.get("confirm", ["0"])[0] in {"1", "true", "yes"}
    event_id = query.get("event_id", [None])[0]
    destination = query.get("destination", ["ics"])[0]
    if destination != "ics":
        h.send_json({"error": "only local ICS export is available without an authenticated calendar client"}, status=400)
        return
    try:
        events = events_from_calendar_rows(db.list_calendar_drafts(h.paths, limit=200), event_id=event_id)
        if not events:
            h.send_json({"error": "no calendar drafts found"}, status=404)
            return
        draft = CalendarDraft(events=tuple(events))
        output_path = h.paths.artifacts / "calendar" / "lifeagent-deadlines.ics"
        result = sync_calendar_draft(
            h.paths,
            draft,
            IcsFileCalendarAdapter(output_path),
            confirmed=confirmed,
            confirmation_id=query.get("confirmation_id", [""])[0] if confirmed else "",
            actor="dashboard",
        )
        if result.allowed:
            for synced_event_id in result.event_ids:
                db.update_calendar_draft_sync_state(
                    h.paths,
                    event_id=synced_event_id,
                    sync_state="ics_exported",
                    status="synced",
                    updated_at=utc_now(),
                )
        h.send_json(result.__dict__)
    except Exception as error:  # noqa: BLE001 - fail-soft API surface
        h.send_json({"error": str(error)}, status=500)


def handle_calendar_unconfirm(h: "Handler", parsed: "ParseResult") -> None:
    # local undo for "加入日历": revert a confirmed draft back to a pending
    # suggestion by resetting its sync state and removing the calendar.sync
    # approval. Local-only; the already-exported ICS file is left in place.
    query = parse_qs(parsed.query)
    event_id = query.get("event_id", [""])[0]
    if not event_id:
        h.send_json({"error": "event_id query parameter required"}, status=400)
        return
    try:
        now = utc_now()
        db.update_calendar_draft_sync_state(
            h.paths,
            event_id=event_id,
            sync_state="local_draft",
            status="draft",
            updated_at=now,
        )
        removed = db.delete_calendar_sync_approvals(h.paths, event_id=event_id)
        db.insert_audit_event(
            h.paths,
            action="calendar.unsync",
            actor="dashboard",
            subject=event_id,
            capability="calendar_draft",
            side_effect="local_db_write",
            allowed=True,
            confirmation_id="",
            metadata={"removed_approvals": removed, "external_write": False},
            created_at=now,
        )
        h.send_json({"reverted": True, "event_id": event_id, "removed_approvals": removed, "external_writes_performed": False})
    except Exception as error:  # noqa: BLE001 - fail-soft API surface
        h.send_json({"error": str(error)}, status=500)


def handle_calendar_drafts_update(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    event_id = query.get("event_id", [""])[0]
    if not event_id:
        h.send_json({"error": "event_id query parameter required"}, status=400)
        return
    try:
        updated_at = utc_now()
        updated = db.update_calendar_draft(
            h.paths,
            event_id=event_id,
            title=query.get("title", [None])[0],
            date_text=query.get("date", [None])[0],
            severity=query.get("severity", [None])[0],
            status="draft",
            sync_state="local_draft",
            updated_at=updated_at,
        )
        if not updated:
            h.send_json({"error": "calendar draft not found", "event_id": event_id}, status=404)
            return
        db.insert_audit_event(
            h.paths,
            action="calendar.edit",
            actor="dashboard",
            subject=event_id,
            capability="calendar_draft",
            side_effect="local_db_write",
            allowed=True,
            confirmation_id="",
            metadata={
                "title": updated.get("title"),
                "date_text": updated.get("date_text"),
                "severity": updated.get("severity"),
                "sync_state": updated.get("sync_state"),
                "external_write": False,
            },
            created_at=updated_at,
        )
        h.send_json({"updated": updated, "external_write": False})
    except Exception as error:  # noqa: BLE001 - fail-soft API surface
        h.send_json({"error": str(error)}, status=500)
