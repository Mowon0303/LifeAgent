"""Queries for ``task_reviews`` (per-task review state)."""

from __future__ import annotations

from typing import Any

from ..config import Paths
from .base import decode_row, decode_rows, open_db


def upsert_task_review(
    paths: Paths,
    *,
    task_id: str,
    status: str,
    note: str,
    actor: str,
    updated_at: str,
) -> int:
    with open_db(paths) as conn:
        existing = conn.execute("SELECT id FROM task_reviews WHERE task_id = ?", (task_id,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE task_reviews
                SET status = ?, note = ?, actor = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (status, note, actor, updated_at, task_id),
            )
            return int(existing["id"])
        cursor = conn.execute(
            """
            INSERT INTO task_reviews(task_id, status, note, actor, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (task_id, status, note, actor, updated_at),
        )
        return int(cursor.lastrowid)


def get_task_review(paths: Paths, *, task_id: str) -> dict[str, Any] | None:
    with open_db(paths) as conn:
        row = conn.execute("SELECT * FROM task_reviews WHERE task_id = ?", (task_id,)).fetchone()
    return decode_row(row)


def delete_task_review(paths: Paths, *, task_id: str) -> int:
    with open_db(paths) as conn:
        cursor = conn.execute("DELETE FROM task_reviews WHERE task_id = ?", (task_id,))
        return int(cursor.rowcount)


def list_task_reviews(paths: Paths, *, limit: int = 500) -> list[dict[str, Any]]:
    with open_db(paths) as conn:
        rows = conn.execute(
            "SELECT * FROM task_reviews ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return decode_rows(rows)
