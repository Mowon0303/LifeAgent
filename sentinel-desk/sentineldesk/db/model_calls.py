"""Queries for the ``model_calls`` ledger (provider/model usage telemetry)."""

from __future__ import annotations

import sqlite3
from typing import Any

from ..config import Paths
from .base import open_db


def insert_model_call(
    paths: Paths,
    *,
    created_at: str,
    provider: str,
    model: str,
    stage: str,
    intent: str,
    status: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    duration_ms: int = 0,
    detail: str = "",
) -> int:
    with open_db(paths) as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO model_calls(
                    created_at, provider, model, stage, intent, status,
                    prompt_tokens, completion_tokens, duration_ms, detail
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    provider,
                    model,
                    stage,
                    intent,
                    status,
                    int(prompt_tokens),
                    int(completion_tokens),
                    int(duration_ms),
                    detail,
                ),
            )
            return int(cursor.lastrowid)
        except sqlite3.OperationalError as exc:
            if "readonly" in str(exc).lower():
                return 0
            raise


def list_model_calls(paths: Paths, *, limit: int = 100) -> list[dict[str, Any]]:
    with open_db(paths) as conn:
        rows = conn.execute(
            """
            SELECT created_at, provider, model, stage, intent, status,
                   prompt_tokens, completion_tokens, duration_ms, detail
            FROM model_calls
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def model_calls_summary(paths: Paths) -> dict[str, Any]:
    with open_db(paths) as conn:
        totals = conn.execute(
            """
            SELECT COUNT(*) AS call_count,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(duration_ms), 0) AS duration_ms
            FROM model_calls
            """
        ).fetchone()
        by_status_rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM model_calls GROUP BY status ORDER BY count DESC"
        ).fetchall()
        by_model_rows = conn.execute(
            """
            SELECT provider, model, COUNT(*) AS count,
                   COALESCE(SUM(prompt_tokens + completion_tokens), 0) AS total_tokens,
                   COALESCE(AVG(duration_ms), 0) AS avg_duration_ms
            FROM model_calls
            GROUP BY provider, model
            ORDER BY count DESC
            """
        ).fetchall()
    refined = sum(row["count"] for row in by_status_rows if row["status"] == "ok")
    call_count = int(totals["call_count"])
    return {
        "call_count": call_count,
        "prompt_tokens": int(totals["prompt_tokens"]),
        "completion_tokens": int(totals["completion_tokens"]),
        "total_tokens": int(totals["prompt_tokens"]) + int(totals["completion_tokens"]),
        "total_duration_ms": int(totals["duration_ms"]),
        "refine_success_rate": (refined / call_count) if call_count else None,
        "by_status": {row["status"]: row["count"] for row in by_status_rows},
        "by_model": [dict(row) for row in by_model_rows],
    }
