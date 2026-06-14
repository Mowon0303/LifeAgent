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
        # A user-created event stays approved when edited; an AI deadline draft is
        # reset to a pending local draft so the user re-confirms the changed date.
        is_user = query.get("user", ["0"])[0] in {"1", "true", "yes"}
        updated = db.update_calendar_draft(
            h.paths,
            event_id=event_id,
            title=query.get("title", [None])[0],
            date_text=query.get("date", [None])[0],
            severity=query.get("severity", [None])[0],
            status=None if is_user else "draft",
            sync_state=None if is_user else "local_draft",
            start_time=query.get("start", [None])[0],
            end_time=query.get("end", [None])[0],
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


def handle_calendar_create(h: "Handler", parsed: "ParseResult") -> None:
    """Create a user-authored calendar event. Unlike AI deadline drafts it is
    approved on creation (the user is the author), so it shows as a confirmed
    event immediately. Writes only the local SQLite draft + an audit row."""
    import hashlib

    from ..calendar.view import parse_deadline_date

    query = parse_qs(parsed.query)
    title = query.get("title", [""])[0].strip()
    date_text = query.get("date", [""])[0].strip()
    if not title or not date_text:
        h.send_json({"error": "title and date are required"}, status=400)
        return
    if not parse_deadline_date(date_text):
        h.send_json({"error": "date is not a recognizable calendar date (use YYYY-MM-DD)"}, status=400)
        return
    try:
        now = utc_now()
        start_time = query.get("start", [""])[0].strip()
        end_time = query.get("end", [""])[0].strip()
        severity = (query.get("severity", ["user"])[0] or "user").strip()
        event_id = "user:" + hashlib.sha256(
            "|".join([title, date_text, start_time, now]).encode("utf-8")
        ).hexdigest()[:16]
        db.upsert_calendar_draft(
            h.paths,
            event={
                "event_id": event_id,
                "title": title,
                "date_text": date_text,
                "severity": severity,
                "confidence": 1.0,
                "status": "approved",
                "evidence_uri": "",
                "source_ids": ["user:created"],
                "reminders": [],
                "start_time": start_time,
                "end_time": end_time,
            },
            created_at=now,
            sync_state="user_created",  # != local_draft -> approval_state approved -> solid on the board
        )
        db.insert_audit_event(
            h.paths,
            action="calendar.create",
            actor="dashboard",
            subject=event_id,
            capability="calendar_draft",
            side_effect="local_db_write",
            allowed=True,
            confirmation_id="",
            metadata={"title": title, "date_text": date_text, "external_write": False},
            created_at=now,
        )
        h.send_json({
            "created": {
                "event_id": event_id, "title": title, "date_text": date_text,
                "start_time": start_time, "end_time": end_time,
            },
            "external_write": False,
        })
    except Exception as error:  # noqa: BLE001 - fail-soft API surface
        h.send_json({"error": str(error)}, status=500)


def handle_calendar_delete(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    event_id = query.get("event_id", [""])[0]
    if not event_id:
        h.send_json({"error": "event_id query parameter required"}, status=400)
        return
    try:
        now = utc_now()
        removed = db.delete_calendar_draft(h.paths, event_id=event_id)
        if not removed:
            h.send_json({"error": "calendar event not found", "event_id": event_id}, status=404)
            return
        db.insert_audit_event(
            h.paths,
            action="calendar.delete",
            actor="dashboard",
            subject=event_id,
            capability="calendar_draft",
            side_effect="local_db_write",
            allowed=True,
            confirmation_id="",
            metadata={"external_write": False},
            created_at=now,
        )
        h.send_json({"deleted": event_id, "external_write": False})
    except Exception as error:  # noqa: BLE001 - fail-soft API surface
        h.send_json({"error": str(error)}, status=500)
