"""Shared database foundation: schema, connection handling, and JSON codecs.

The repository modules in this package (targets, runs, email, calendar, audit,
reviews, rag, connectors, model_calls) own the queries for one aggregate each
and import the connection + codec helpers from here. ``db/__init__.py`` re-exports
every public symbol so callers keep using the flat ``db.<func>`` surface.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable, Iterator

from ..config import Paths


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
    # timeout sets SQLite's busy_timeout: under the threaded HTTP server each
    # request thread opens its own connection, so a writer that finds the db
    # locked waits up to 5s instead of failing loud with "database is locked".
    conn = sqlite3.connect(paths.database, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets concurrent readers proceed while a single writer commits, which
    # matches the read-heavy dashboard + occasional write workload. synchronous
    # = NORMAL is the safe, standard pairing with WAL.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
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
        # Timed user-created events (deadlines are date-only; these stay empty for them).
        _ensure_column(conn, "calendar_drafts", "start_time", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "calendar_drafts", "end_time", "TEXT NOT NULL DEFAULT ''")


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
