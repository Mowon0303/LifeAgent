"""Queries for monitor ``runs`` and their ``trace_events``."""

from __future__ import annotations

from typing import Any

from ..config import Paths
from .base import _json, decode_row, decode_rows, open_db


def latest_run(paths: Paths, target_id: int) -> dict[str, Any] | None:
    with open_db(paths) as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE target_id = ? ORDER BY id DESC LIMIT 1",
            (target_id,),
        ).fetchone()
    return decode_row(row)


def insert_run(paths: Paths, run: dict[str, Any]) -> int:
    with open_db(paths) as conn:
        cursor = conn.execute(
            """
            INSERT INTO runs(
                run_id, target_id, captured_at, final_url, title, text_hash,
                text_path, html_path, screenshot_path, health_json, status_json,
                deadlines_json, diff_json, alert_json, evidence_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run["run_id"],
                run["target_id"],
                run["captured_at"],
                run["final_url"],
                run["title"],
                run["text_hash"],
                str(run["text_path"]),
                str(run["html_path"]),
                str(run.get("screenshot_path") or ""),
                _json(run["health"]),
                _json(run["status"]),
                _json(run["deadlines"]),
                _json(run["diff"]),
                _json(run["alert"]),
                _json(run["evidence"]),
            ),
        )
        conn.execute(
            "UPDATE targets SET last_run_at = ?, last_health_state = ?, last_alert_level = ? WHERE id = ?",
            (run["captured_at"], run["health"]["state"], run["alert"]["level"], run["target_id"]),
        )
        return int(cursor.lastrowid)


def list_runs(paths: Paths, target_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with open_db(paths) as conn:
        if target_id is None:
            rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM runs WHERE target_id = ? ORDER BY id DESC LIMIT ?",
                (target_id, limit),
            ).fetchall()
    return decode_rows(rows)


def get_run(paths: Paths, run_id: str) -> dict[str, Any] | None:
    with open_db(paths) as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return decode_row(row)


def list_alerts(paths: Paths, limit: int = 50) -> list[dict[str, Any]]:
    runs = list_runs(paths, limit=limit)
    return [run for run in runs if run.get("alert", {}).get("level") not in {"none", "baseline"}]


def insert_trace(paths: Paths, *, run_id: str, stage: str, input_summary: str, output_summary: str, created_at: str) -> None:
    with open_db(paths) as conn:
        conn.execute(
            """
            INSERT INTO trace_events(run_id, stage, input_summary, output_summary, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, stage, input_summary, output_summary, created_at),
        )


def list_traces(paths: Paths, run_id: str) -> list[dict[str, Any]]:
    with open_db(paths) as conn:
        rows = conn.execute("SELECT * FROM trace_events WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
    return decode_rows(rows)
