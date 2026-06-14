"""Queries for the ``targets`` table (monitored portal definitions)."""

from __future__ import annotations

from typing import Any

from ..config import Paths
from .base import decode_row, decode_rows, open_db


def upsert_target(paths: Paths, *, name: str, url: str, kind: str, high_stakes: bool, created_at: str) -> int:
    with open_db(paths) as conn:
        existing = conn.execute("SELECT id FROM targets WHERE name = ?", (name,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE targets SET url = ?, kind = ?, high_stakes = ?, enabled = 1 WHERE id = ?",
                (url, kind, 1 if high_stakes else 0, existing["id"]),
            )
            return int(existing["id"])
        cursor = conn.execute(
            """
            INSERT INTO targets(name, url, kind, high_stakes, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, url, kind, 1 if high_stakes else 0, created_at),
        )
        return int(cursor.lastrowid)


def list_targets(paths: Paths) -> list[dict[str, Any]]:
    with open_db(paths) as conn:
        rows = conn.execute("SELECT * FROM targets ORDER BY id").fetchall()
    return decode_rows(rows)


def get_target(paths: Paths, *, target_id: int | None = None, name: str | None = None) -> dict[str, Any] | None:
    with open_db(paths) as conn:
        if target_id is not None:
            row = conn.execute("SELECT * FROM targets WHERE id = ?", (target_id,)).fetchone()
        elif name is not None:
            row = conn.execute("SELECT * FROM targets WHERE name = ?", (name,)).fetchone()
        else:
            raise ValueError("target_id or name required")
    return decode_row(row)
