"""Queries for ``audit_events`` and ``approval_records`` (the safety ledger)."""

from __future__ import annotations

import json
from typing import Any

from ..config import Paths
from .base import _json, decode_row, decode_rows, open_db


def insert_audit_event(
    paths: Paths,
    *,
    action: str,
    actor: str,
    subject: str,
    capability: str,
    side_effect: str,
    allowed: bool,
    confirmation_id: str,
    metadata: dict[str, Any],
    created_at: str,
) -> int:
    with open_db(paths) as conn:
        cursor = conn.execute(
            """
            INSERT INTO audit_events(
                action, actor, subject, capability, side_effect, allowed,
                confirmation_id, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action,
                actor,
                subject,
                capability,
                side_effect,
                1 if allowed else 0,
                confirmation_id,
                _json(metadata),
                created_at,
            ),
        )
        return int(cursor.lastrowid)


def list_audit_events(paths: Paths, *, limit: int = 100) -> list[dict[str, Any]]:
    with open_db(paths) as conn:
        rows = conn.execute(
            "SELECT * FROM audit_events ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return decode_rows(rows)


def get_audit_event(paths: Paths, *, audit_id: int) -> dict[str, Any] | None:
    with open_db(paths) as conn:
        row = conn.execute("SELECT * FROM audit_events WHERE id = ?", (audit_id,)).fetchone()
    return decode_row(row)


def insert_approval_record(
    paths: Paths,
    *,
    confirmation_id: str,
    actor: str,
    action: str,
    subject: str,
    capability: str,
    side_effect: str,
    status: str,
    evidence_refs: list[str],
    metadata: dict[str, Any],
    created_at: str,
    consumed_at: str,
) -> int:
    with open_db(paths) as conn:
        cursor = conn.execute(
            """
            INSERT INTO approval_records(
                confirmation_id, actor, action, subject, capability, side_effect,
                status, evidence_refs_json, metadata_json, created_at, consumed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                confirmation_id,
                actor,
                action,
                subject,
                capability,
                side_effect,
                status,
                _json(evidence_refs),
                _json(metadata),
                created_at,
                consumed_at,
            ),
        )
        return int(cursor.lastrowid)


def list_approval_records(paths: Paths, *, limit: int = 100) -> list[dict[str, Any]]:
    with open_db(paths) as conn:
        rows = conn.execute(
            "SELECT * FROM approval_records ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return decode_rows(rows)


def delete_calendar_sync_approvals(paths: Paths, *, event_id: str) -> int:
    """Remove the calendar.sync approval(s) that confirmed a given draft event so the
    event reverts to a pending suggestion. Used by the local 'undo add to calendar' flow."""
    if not event_id:
        return 0
    removed = 0
    with open_db(paths) as conn:
        rows = conn.execute(
            "SELECT id, metadata_json FROM approval_records WHERE action = 'calendar.sync'"
        ).fetchall()
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, ValueError):
                metadata = {}
            if event_id in [str(eid) for eid in metadata.get("event_ids", [])]:
                conn.execute("DELETE FROM approval_records WHERE id = ?", (row["id"],))
                removed += 1
    return removed


def approval_record_exists(paths: Paths, *, confirmation_id: str, action: str, subject: str) -> bool:
    if not confirmation_id:
        return False
    with open_db(paths) as conn:
        row = conn.execute(
            """
            SELECT id FROM approval_records
            WHERE confirmation_id = ? AND action = ? AND subject = ?
            LIMIT 1
            """,
            (confirmation_id, action, subject),
        ).fetchone()
    return row is not None
