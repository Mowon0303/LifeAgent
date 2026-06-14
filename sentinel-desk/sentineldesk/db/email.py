"""Queries for stored ``email_messages`` and their extracted facts."""

from __future__ import annotations

from typing import Any, Iterable

from ..config import Paths
from .base import _email_fact_dict, _json, decode_rows, open_db


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
