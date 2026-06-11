from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sentineldesk import db
from sentineldesk.calendar.draft import draft_events_from_facts
from sentineldesk.config import Paths
from sentineldesk.extract import utc_now

from .attachments import parse_attachment_files
from .extract import extract_email_facts
from .models import EmailMessage


def load_email_json(path: str | Path) -> list[EmailMessage]:
    source_path = Path(path)
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    raw_messages = raw.get("messages", []) if isinstance(raw, dict) else raw
    messages: list[EmailMessage] = []
    for index, item in enumerate(raw_messages):
        if not isinstance(item, dict):
            continue
        messages.append(_message_from_dict(item, index, base_dir=source_path.parent))
    return messages


def ingest_messages(paths: Paths, messages: list[EmailMessage], *, ingested_at: str | None = None) -> dict[str, Any]:
    db.init_db(paths)
    timestamp = ingested_at or utc_now()
    message_row_ids: list[int] = []
    calendar_row_ids: list[int] = []
    fact_count = 0

    for message in messages:
        facts = extract_email_facts(message)
        fact_count += len(facts)
        message_row_ids.append(db.upsert_email_message(paths, message=message, facts=facts, ingested_at=timestamp))

        draft = draft_events_from_facts(facts, evidence_uri=message.source_id)
        for event in draft.events:
            calendar_row_ids.append(
                db.upsert_calendar_draft(
                    paths,
                    event=event,
                    created_at=timestamp,
                    updated_at=timestamp,
                    sync_state="local_draft",
                )
            )

    db.insert_audit_event(
        paths,
        action="email.ingest",
        actor="system",
        subject="email_messages",
        capability="email_read",
        side_effect="local_db_write",
        allowed=True,
        confirmation_id="",
        metadata={
            "messages_seen": len(messages),
            "messages_persisted": len(message_row_ids),
            "facts_extracted": fact_count,
            "deadline_events_drafted": len(calendar_row_ids),
        },
        created_at=timestamp,
    )
    return {
        "messages_seen": len(messages),
        "messages_persisted": len(message_row_ids),
        "facts_extracted": fact_count,
        "deadline_events_drafted": len(calendar_row_ids),
        "message_row_ids": message_row_ids,
        "calendar_draft_row_ids": calendar_row_ids,
        "confirmation_required": bool(calendar_row_ids),
    }


def sync_connector(
    paths: Paths,
    connector: Any,
    request: Any,
    *,
    account_id: str = "default",
    ingested_at: str | None = None,
) -> dict[str, Any]:
    db.init_db(paths)
    timestamp = ingested_at or utc_now()
    result = connector.search(request)
    ingest_summary = ingest_messages(paths, list(result.messages), ingested_at=timestamp)
    resolved_account_id = result.account_id or account_id
    if result.cursor:
        db.upsert_connector_state(
            paths,
            connector=result.connector,
            account_id=resolved_account_id,
            cursor=result.cursor,
            scopes=list(result.scopes),
            metadata={
                "source_type": result.source_type,
                "trust_label": result.trust_label,
                "warnings": list(result.warnings),
                **(result.metadata or {}),
            },
            updated_at=timestamp,
        )
    db.insert_audit_event(
        paths,
        action="email.connector.sync",
        actor="system",
        subject=f"{result.connector}:{resolved_account_id}",
        capability="email_read",
        side_effect="local_db_write",
        allowed=True,
        confirmation_id="",
        metadata={
            "connector": result.connector,
            "account_id": resolved_account_id,
            "message_count": len(result.messages),
            "cursor_saved": bool(result.cursor),
            "scopes": list(result.scopes),
            "warnings": list(result.warnings),
        },
        created_at=timestamp,
    )
    return {
        **ingest_summary,
        "connector": result.connector,
        "account_id": resolved_account_id,
        "cursor_saved": bool(result.cursor),
        "cursor": result.cursor,
        "scopes": list(result.scopes),
    }


def _message_from_dict(item: dict[str, Any], index: int, *, base_dir: Path) -> EmailMessage:
    attachment_texts = list(item.get("attachment_texts") or [])
    attachment_names = list(item.get("attachment_names") or [])
    for attachment in parse_attachment_files(tuple(item.get("attachment_paths") or []), base_dir=base_dir):
        attachment_names.append(attachment.name)
        if attachment.text:
            attachment_texts.append(attachment.text)
    return EmailMessage(
        message_id=str(item.get("message_id") or item.get("id") or f"message-{index}"),
        thread_id=str(item.get("thread_id") or item.get("thread") or "default"),
        sender=str(item.get("sender") or item.get("from") or ""),
        subject=str(item.get("subject") or ""),
        received_at=str(item.get("received_at") or item.get("date") or ""),
        body_text=str(item.get("body_text") or item.get("body") or ""),
        attachment_texts=tuple(attachment_texts),
        attachment_names=tuple(attachment_names),
        source_type=str(item.get("source_type") or "email"),
        trust_label=str(item.get("trust_label") or "email_unverified"),
    )
