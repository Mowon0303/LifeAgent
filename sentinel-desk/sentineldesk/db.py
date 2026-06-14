from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import Paths


SCHEMA = """
CREATE TABLE IF NOT EXISTS targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'generic',
    enabled INTEGER NOT NULL DEFAULT 1,
    high_stakes INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_run_at TEXT,
    last_health_state TEXT,
    last_alert_level TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    target_id INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    final_url TEXT NOT NULL,
    title TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    text_path TEXT NOT NULL,
    html_path TEXT NOT NULL,
    screenshot_path TEXT,
    health_json TEXT NOT NULL,
    status_json TEXT NOT NULL,
    deadlines_json TEXT NOT NULL,
    diff_json TEXT NOT NULL,
    alert_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    FOREIGN KEY(target_id) REFERENCES targets(id)
);

CREATE TABLE IF NOT EXISTS trace_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    input_summary TEXT NOT NULL,
    output_summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS email_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    thread_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    received_at TEXT NOT NULL,
    body_text TEXT NOT NULL,
    attachment_names_json TEXT NOT NULL,
    attachment_texts_json TEXT NOT NULL,
    labels_json TEXT NOT NULL DEFAULT '[]',
    list_unsubscribe TEXT NOT NULL DEFAULT '',
    facts_json TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_email_messages_thread ON email_messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_received ON email_messages(received_at);

CREATE TABLE IF NOT EXISTS calendar_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    date_text TEXT NOT NULL,
    severity TEXT NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    evidence_uri TEXT NOT NULL,
    source_ids_json TEXT NOT NULL,
    reminders_json TEXT NOT NULL,
    sync_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_calendar_drafts_date ON calendar_drafts(date_text);
CREATE INDEX IF NOT EXISTS idx_calendar_drafts_status ON calendar_drafts(status);

CREATE TABLE IF NOT EXISTS task_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    note TEXT NOT NULL,
    actor TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_reviews_status ON task_reviews(status);
CREATE INDEX IF NOT EXISTS idx_task_reviews_updated ON task_reviews(updated_at);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    subject TEXT NOT NULL,
    capability TEXT NOT NULL,
    side_effect TEXT NOT NULL,
    allowed INTEGER NOT NULL,
    confirmation_id TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_action ON audit_events(action);

CREATE TABLE IF NOT EXISTS approval_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    confirmation_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    subject TEXT NOT NULL,
    capability TEXT NOT NULL,
    side_effect TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    consumed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_approval_records_created ON approval_records(created_at);
CREATE INDEX IF NOT EXISTS idx_approval_records_action ON approval_records(action);
CREATE INDEX IF NOT EXISTS idx_approval_records_confirmation ON approval_records(confirmation_id);

CREATE TABLE IF NOT EXISTS rag_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,
    trust_label TEXT NOT NULL,
    title TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    indexed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL UNIQUE,
    text TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    indexed_at TEXT NOT NULL,
    embedding_json TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(source_id) REFERENCES rag_documents(source_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_source ON rag_chunks(source_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_indexed ON rag_chunks(indexed_at);

CREATE TABLE IF NOT EXISTS connector_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connector TEXT NOT NULL,
    account_id TEXT NOT NULL,
    cursor TEXT NOT NULL,
    scopes_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(connector, account_id)
);

CREATE INDEX IF NOT EXISTS idx_connector_states_updated ON connector_states(updated_at);

CREATE TABLE IF NOT EXISTS integration_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id TEXT NOT NULL UNIQUE,
    suite TEXT NOT NULL,
    status TEXT NOT NULL,
    checks_json TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_integration_verifications_created ON integration_verifications(created_at);
CREATE INDEX IF NOT EXISTS idx_integration_verifications_suite ON integration_verifications(suite);

CREATE TABLE IF NOT EXISTS model_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    stage TEXT NOT NULL,
    intent TEXT NOT NULL,
    status TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_model_calls_created ON model_calls(created_at);
"""


def connect(paths: Paths) -> sqlite3.Connection:
    paths.home.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(paths.database)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def open_db(paths: Paths) -> Iterator[sqlite3.Connection]:
    conn = connect(paths)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(paths: Paths) -> None:
    with open_db(paths) as conn:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "email_messages", "labels_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "email_messages", "list_unsubscribe", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "rag_chunks", "embedding_json", "TEXT NOT NULL DEFAULT ''")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        except sqlite3.OperationalError as exc:
            if "readonly" in str(exc).lower():
                return
            raise


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _decode_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def decode_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = {key: row[key] for key in row.keys()}
    for key in list(data):
        if key.endswith("_json"):
            data[key[:-5]] = _decode_json(data.pop(key), {})
    return data


def decode_rows(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [decode_row(row) or {} for row in rows]


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


def _object_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    return dict(value.__dict__)


def _email_fact_dict(fact: Any) -> dict[str, Any]:
    data = _object_dict(fact)
    data["metadata"] = dict(data.get("metadata") or {})
    return data


def _calendar_event_dict(event: Any) -> dict[str, Any]:
    data = _object_dict(event)
    data["source_ids"] = list(data.get("source_ids") or [])
    data["reminders"] = [dict(item) for item in data.get("reminders") or []]
    return data


def upsert_email_message(paths: Paths, *, message: Any, facts: Iterable[Any], ingested_at: str) -> int:
    attachment_names = list(getattr(message, "attachment_names", ()) or ())
    attachment_texts = list(getattr(message, "attachment_texts", ()) or ())
    labels = list(getattr(message, "labels", ()) or ())
    list_unsubscribe = str(getattr(message, "list_unsubscribe", "") or "")
    fact_payload = [_email_fact_dict(fact) for fact in facts]
    values = (
        str(getattr(message, "thread_id", "")),
        str(getattr(message, "sender", "")),
        str(getattr(message, "subject", "")),
        str(getattr(message, "received_at", "")),
        str(getattr(message, "body_text", "")),
        _json(attachment_names),
        _json(attachment_texts),
        _json(labels),
        list_unsubscribe,
        _json(fact_payload),
        ingested_at,
        str(getattr(message, "message_id", "")),
    )
    with open_db(paths) as conn:
        existing = conn.execute(
            "SELECT id FROM email_messages WHERE message_id = ?",
            (str(getattr(message, "message_id", "")),),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE email_messages
                SET thread_id = ?, sender = ?, subject = ?, received_at = ?, body_text = ?,
                    attachment_names_json = ?, attachment_texts_json = ?,
                    labels_json = ?, list_unsubscribe = ?,
                    facts_json = ?, ingested_at = ?
                WHERE message_id = ?
                """,
                values,
            )
            return int(existing["id"])
        cursor = conn.execute(
            """
            INSERT INTO email_messages(
                thread_id, sender, subject, received_at, body_text,
                attachment_names_json, attachment_texts_json,
                labels_json, list_unsubscribe,
                facts_json, ingested_at, message_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        return int(cursor.lastrowid)


def list_email_messages(paths: Paths, *, limit: int = 50) -> list[dict[str, Any]]:
    with open_db(paths) as conn:
        rows = conn.execute("SELECT * FROM email_messages ORDER BY received_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
    return decode_rows(rows)


def list_email_facts(paths: Paths, *, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    messages = list_email_messages(paths, limit=max(limit, 100))
    facts: list[dict[str, Any]] = []
    for message in messages:
        for fact in message.get("facts", []):
            if kind and fact.get("kind") != kind:
                continue
            enriched = dict(fact)
            enriched["message_id"] = message.get("message_id")
            enriched["thread_id"] = message.get("thread_id")
            enriched["subject"] = message.get("subject")
            enriched["sender"] = message.get("sender")
            enriched["message_received_at"] = message.get("received_at")
            facts.append(enriched)
    facts.sort(key=lambda item: (str(item.get("received_at") or ""), str(item.get("source_id") or "")), reverse=True)
    return facts[:limit]


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
                    evidence_uri = ?, source_ids_json = ?, reminders_json = ?, sync_state = ?, updated_at = ?
                WHERE event_id = ?
                """,
                values,
            )
            return int(existing["id"])
        cursor = conn.execute(
            """
            INSERT INTO calendar_drafts(
                title, date_text, severity, confidence, status, evidence_uri,
                source_ids_json, reminders_json, sync_state, updated_at, event_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        conn.execute(
            """
            UPDATE calendar_drafts
            SET title = ?, date_text = ?, severity = ?, status = ?, sync_state = ?, updated_at = ?
            WHERE event_id = ?
            """,
            (next_title, next_date_text, next_severity, next_status, next_sync_state, updated_at, event_id),
        )
        updated = conn.execute("SELECT * FROM calendar_drafts WHERE event_id = ?", (event_id,)).fetchone()
    return decode_row(updated)


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


def upsert_rag_document(
    paths: Paths,
    *,
    source_id: str,
    source_type: str,
    trust_label: str,
    title: str,
    metadata: dict[str, Any],
    chunks: list[dict[str, Any]],
    indexed_at: str,
) -> int:
    with open_db(paths) as conn:
        existing = conn.execute("SELECT id FROM rag_documents WHERE source_id = ?", (source_id,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE rag_documents
                SET source_type = ?, trust_label = ?, title = ?, metadata_json = ?, indexed_at = ?
                WHERE source_id = ?
                """,
                (source_type, trust_label, title, _json(metadata), indexed_at, source_id),
            )
            document_id = int(existing["id"])
            conn.execute("DELETE FROM rag_chunks WHERE source_id = ?", (source_id,))
        else:
            cursor = conn.execute(
                """
                INSERT INTO rag_documents(source_id, source_type, trust_label, title, metadata_json, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (source_id, source_type, trust_label, title, _json(metadata), indexed_at),
            )
            document_id = int(cursor.lastrowid)
        for chunk in chunks:
            embedding = chunk.get("embedding")
            conn.execute(
                """
                INSERT INTO rag_chunks(source_id, chunk_id, text, warnings_json, token_count, indexed_at, embedding_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    str(chunk["chunk_id"]),
                    str(chunk["text"]),
                    _json(list(chunk.get("warnings", []))),
                    int(chunk.get("token_count", 0)),
                    indexed_at,
                    _json(list(embedding)) if embedding else "",
                ),
            )
        return document_id


def list_rag_documents(paths: Paths, *, limit: int = 100) -> list[dict[str, Any]]:
    with open_db(paths) as conn:
        rows = conn.execute(
            "SELECT * FROM rag_documents ORDER BY indexed_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return decode_rows(rows)


def list_rag_chunks(paths: Paths, *, limit: int = 200) -> list[dict[str, Any]]:
    with open_db(paths) as conn:
        rows = conn.execute(
            """
            SELECT c.*, d.source_type, d.trust_label, d.title, d.metadata_json
            FROM rag_chunks c
            JOIN rag_documents d ON d.source_id = c.source_id
            ORDER BY c.indexed_at DESC, c.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return decode_rows(rows)


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
