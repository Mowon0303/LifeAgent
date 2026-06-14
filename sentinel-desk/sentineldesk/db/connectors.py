"""Queries for ``connector_states`` and ``integration_verifications``."""

from __future__ import annotations

from typing import Any

from ..config import Paths
from .base import _json, decode_row, decode_rows, open_db


def upsert_connector_state(
    paths: Paths,
    *,
    connector: str,
    account_id: str,
    cursor: str,
    scopes: list[str],
    metadata: dict[str, Any],
    updated_at: str,
) -> int:
    with open_db(paths) as conn:
        existing = conn.execute(
            "SELECT id FROM connector_states WHERE connector = ? AND account_id = ?",
            (connector, account_id),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE connector_states
                SET cursor = ?, scopes_json = ?, metadata_json = ?, updated_at = ?
                WHERE connector = ? AND account_id = ?
                """,
                (cursor, _json(scopes), _json(metadata), updated_at, connector, account_id),
            )
            return int(existing["id"])
        cursor_obj = conn.execute(
            """
            INSERT INTO connector_states(connector, account_id, cursor, scopes_json, metadata_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (connector, account_id, cursor, _json(scopes), _json(metadata), updated_at),
        )
        return int(cursor_obj.lastrowid)


def get_connector_state(paths: Paths, *, connector: str, account_id: str) -> dict[str, Any] | None:
    with open_db(paths) as conn:
        row = conn.execute(
            "SELECT * FROM connector_states WHERE connector = ? AND account_id = ?",
            (connector, account_id),
        ).fetchone()
    return decode_row(row)


def list_connector_states(paths: Paths, *, limit: int = 100) -> list[dict[str, Any]]:
    with open_db(paths) as conn:
        rows = conn.execute(
            "SELECT * FROM connector_states ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return decode_rows(rows)


def insert_integration_verification(
    paths: Paths,
    *,
    verification_id: str,
    suite: str,
    status: str,
    checks: list[dict[str, Any]],
    artifact_path: str,
    created_at: str,
) -> int:
    with open_db(paths) as conn:
        cursor = conn.execute(
            """
            INSERT INTO integration_verifications(
                verification_id, suite, status, checks_json, artifact_path, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (verification_id, suite, status, _json(checks), artifact_path, created_at),
        )
        return int(cursor.lastrowid)


def list_integration_verifications(paths: Paths, *, limit: int = 50) -> list[dict[str, Any]]:
    with open_db(paths) as conn:
        rows = conn.execute(
            "SELECT * FROM integration_verifications ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return decode_rows(rows)


def get_integration_verification(paths: Paths, verification_id: str) -> dict[str, Any] | None:
    with open_db(paths) as conn:
        row = conn.execute(
            "SELECT * FROM integration_verifications WHERE verification_id = ? LIMIT 1",
            (verification_id,),
        ).fetchone()
    return decode_row(row)
