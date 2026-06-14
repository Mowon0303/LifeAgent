"""Queries for ``calendar_drafts`` (local deadline events before any sync)."""

from __future__ import annotations

from typing import Any

from ..config import Paths
from .base import _calendar_event_dict, _json, decode_row, decode_rows, open_db


def upsert_calendar_draft(
    paths: Paths,
    *,
    event: Any,
    created_at: str,
    updated_at: str | None = None,
    sync_state: str = "local_draft",
) -> int:
    data = _calendar_event_dict(event)
    updated_at = updated_at or created_at
    values = (
        str(data.get("title") or ""),
        str(data.get("date_text") or ""),
        str(data.get("severity") or "medium"),
        float(data.get("confidence") or 0.0),
        str(data.get("status") or "draft"),
        str(data.get("evidence_uri") or ""),
        _json(data.get("source_ids") or []),
        _json(data.get("reminders") or []),
        sync_state,
        str(data.get("start_time") or ""),
        str(data.get("end_time") or ""),
        updated_at,
        str(data.get("event_id") or ""),
    )
    with open_db(paths) as conn:
        existing = conn.execute(
            "SELECT id, created_at FROM calendar_drafts WHERE event_id = ?",
            (str(data.get("event_id") or ""),),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE calendar_drafts
                SET title = ?, date_text = ?, severity = ?, confidence = ?, status = ?,
                    evidence_uri = ?, source_ids_json = ?, reminders_json = ?, sync_state = ?,
                    start_time = ?, end_time = ?, updated_at = ?
                WHERE event_id = ?
                """,
                values,
            )
            return int(existing["id"])
        cursor = conn.execute(
            """
            INSERT INTO calendar_drafts(
                title, date_text, severity, confidence, status, evidence_uri,
                source_ids_json, reminders_json, sync_state, start_time, end_time, updated_at, event_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*values, created_at),
        )
        return int(cursor.lastrowid)


def list_calendar_drafts(paths: Paths, *, limit: int = 100) -> list[dict[str, Any]]:
    with open_db(paths) as conn:
        rows = conn.execute(
            "SELECT * FROM calendar_drafts ORDER BY date_text ASC, updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return decode_rows(rows)


def delete_stale_local_drafts(paths: Paths, *, keep_event_ids: set[str]) -> list[str]:
    """Delete local draft calendar events that a full re-extraction no longer
    produces, returning the removed event ids.

    Only ``local_draft`` rows are eligible: a draft the user already confirmed
    or that synced to an external calendar is never removed here. Callers must
    pass the complete set of event ids re-drafted by the same pass — anything
    outside it is a stale draft whose backing deadline fact disappeared (the
    source was filtered out, or the source message is gone entirely).
    """
    removed: list[str] = []
    with open_db(paths) as conn:
        rows = conn.execute(
            "SELECT event_id FROM calendar_drafts WHERE sync_state = 'local_draft'"
        ).fetchall()
        for row in rows:
            event_id = str(row["event_id"])
            if event_id in keep_event_ids:
                continue
            conn.execute(
                "DELETE FROM calendar_drafts WHERE event_id = ? AND sync_state = 'local_draft'",
                (event_id,),
            )
            removed.append(event_id)
    return removed


def update_calendar_draft(
    paths: Paths,
    *,
    event_id: str,
    updated_at: str,
    title: str | None = None,
    date_text: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    sync_state: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any] | None:
    with open_db(paths) as conn:
        row = conn.execute("SELECT * FROM calendar_drafts WHERE event_id = ?", (event_id,)).fetchone()
        if not row:
            return None
        current = decode_row(row) or {}
        next_title = title if title is not None else str(current.get("title") or "")
        next_date_text = date_text if date_text is not None else str(current.get("date_text") or "")
        next_severity = severity if severity is not None else str(current.get("severity") or "medium")
        next_status = status if status is not None else str(current.get("status") or "draft")
        next_sync_state = sync_state if sync_state is not None else str(current.get("sync_state") or "local_draft")
        next_start = start_time if start_time is not None else str(current.get("start_time") or "")
        next_end = end_time if end_time is not None else str(current.get("end_time") or "")
        conn.execute(
            """
            UPDATE calendar_drafts
            SET title = ?, date_text = ?, severity = ?, status = ?, sync_state = ?,
                start_time = ?, end_time = ?, updated_at = ?
            WHERE event_id = ?
            """,
            (next_title, next_date_text, next_severity, next_status, next_sync_state,
             next_start, next_end, updated_at, event_id),
        )
        updated = conn.execute("SELECT * FROM calendar_drafts WHERE event_id = ?", (event_id,)).fetchone()
    return decode_row(updated)


def delete_calendar_draft(paths: Paths, *, event_id: str) -> bool:
    """Hard-delete a calendar draft (used for user-created events the user removes)."""
    with open_db(paths) as conn:
        cursor = conn.execute("DELETE FROM calendar_drafts WHERE event_id = ?", (event_id,))
        return cursor.rowcount > 0


def update_calendar_draft_sync_state(
    paths: Paths,
    *,
    event_id: str,
    sync_state: str,
    updated_at: str,
    status: str | None = None,
) -> None:
    with open_db(paths) as conn:
        if status is None:
            conn.execute(
                "UPDATE calendar_drafts SET sync_state = ?, updated_at = ? WHERE event_id = ?",
                (sync_state, updated_at, event_id),
            )
        else:
            conn.execute(
                "UPDATE calendar_drafts SET sync_state = ?, status = ?, updated_at = ? WHERE event_id = ?",
                (sync_state, status, updated_at, event_id),
            )
