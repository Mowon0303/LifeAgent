from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from sentineldesk import db
from sentineldesk.calendar.draft import draft_events_from_facts
from sentineldesk.config import Paths
from sentineldesk.extract import utc_now

from .attachments import parse_attachment_files
from .deadline_gate import DeadlineGate, deadline_gate_for_paths
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


def ingest_messages(
    paths: Paths,
    messages: list[EmailMessage],
    *,
    ingested_at: str | None = None,
    deadline_gate: DeadlineGate | None = None,
) -> dict[str, Any]:
    db.init_db(paths)
    timestamp = ingested_at or utc_now()
    active_deadline_gate = deadline_gate if deadline_gate is not None else deadline_gate_for_paths(paths)
    message_row_ids: list[int] = []
    calendar_row_ids: list[int] = []
    fact_count = 0

    for message in messages:
        facts = extract_email_facts(message, deadline_gate=active_deadline_gate)
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


def stored_email_messages(paths: Paths, *, limit: int = 200) -> list[EmailMessage]:
    """Rebuild EmailMessage objects from locally persisted email evidence.

    Lets the assistant answer questions over already-synced mail without a
    fresh export file; trust labels stay at the stored-evidence level.
    """
    db.init_db(paths)
    return [
        _message_from_stored_row(row, preserve_source_labels=False)
        for row in db.list_email_messages(paths, limit=limit)
    ]


def reprocess_stored_messages(
    paths: Paths,
    *,
    limit: int = 500,
    rebuild_calendar_drafts: bool = True,
    ingested_at: str | None = None,
    deadline_gate: DeadlineGate | None = None,
) -> dict[str, Any]:
    """Re-run the current extractor over already persisted local email evidence.

    This lets extractor fixes take effect without another Gmail call. It only
    rewrites local facts and local draft rows; external calendar writes remain
    outside this path.
    """
    db.init_db(paths)
    timestamp = ingested_at or utc_now()
    active_deadline_gate = deadline_gate if deadline_gate is not None else deadline_gate_for_paths(paths)
    rows = db.list_email_messages(paths, limit=limit)
    message_row_ids: list[int] = []
    calendar_row_ids: list[int] = []
    drafted_event_ids: set[str] = set()
    old_fact_count = 0
    new_fact_count = 0
    old_fact_counts: Counter[str] = Counter()
    new_fact_counts: Counter[str] = Counter()

    for row in rows:
        old_facts = row.get("facts") or []
        old_fact_count += len(old_facts)
        for fact in old_facts:
            if isinstance(fact, dict):
                old_fact_counts[str(fact.get("kind") or "unknown")] += 1

        message = _message_from_stored_row(row, preserve_source_labels=True)
        facts = extract_email_facts(message, deadline_gate=active_deadline_gate)
        new_fact_count += len(facts)
        new_fact_counts.update(fact.kind for fact in facts)
        message_row_ids.append(db.upsert_email_message(paths, message=message, facts=facts, ingested_at=timestamp))

        if rebuild_calendar_drafts:
            draft = draft_events_from_facts(facts, evidence_uri=message.source_id)
            for event in draft.events:
                drafted_event_ids.add(str(event.event_id))
                calendar_row_ids.append(
                    db.upsert_calendar_draft(
                        paths,
                        event=event,
                        created_at=timestamp,
                        updated_at=timestamp,
                        sync_state="local_draft",
                    )
                )

    # Garbage-collect drafts a full re-extraction no longer produces (a source
    # the gate now filters, or a message that is gone). Only when this pass saw
    # every stored message (untruncated), so we never delete a still-valid draft
    # for a message left outside the limit window. Confirmed/synced drafts are
    # left untouched by delete_stale_local_drafts.
    removed_draft_ids: list[str] = []
    if rebuild_calendar_drafts and len(rows) < limit:
        removed_draft_ids = db.delete_stale_local_drafts(paths, keep_event_ids=drafted_event_ids)

    db.insert_audit_event(
        paths,
        action="email.reprocess",
        actor="system",
        subject="stored_email_messages",
        capability="email_read",
        side_effect="local_db_write",
        allowed=True,
        confirmation_id="",
        metadata={
            "messages_seen": len(rows),
            "messages_reprocessed": len(message_row_ids),
            "old_facts": old_fact_count,
            "facts_extracted": new_fact_count,
            "deadline_events_drafted": len(calendar_row_ids),
            "stale_drafts_removed": len(removed_draft_ids),
            "rebuild_calendar_drafts": rebuild_calendar_drafts,
            "external_writes_performed": False,
        },
        created_at=timestamp,
    )
    return {
        "mode": "stored_reprocess",
        "external_network": False,
        "messages_seen": len(rows),
        "messages_reprocessed": len(message_row_ids),
        "old_facts": old_fact_count,
        "facts_extracted": new_fact_count,
        "old_fact_counts": dict(sorted(old_fact_counts.items())),
        "fact_counts": dict(sorted(new_fact_counts.items())),
        "deadline_events_drafted": len(calendar_row_ids),
        "stale_drafts_removed": len(removed_draft_ids),
        "message_row_ids": message_row_ids,
        "calendar_draft_row_ids": calendar_row_ids,
        "rebuild_calendar_drafts": rebuild_calendar_drafts,
        "confirmation_required": bool(calendar_row_ids),
        "external_writes_performed": False,
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


def _message_from_stored_row(row: dict[str, Any], *, preserve_source_labels: bool) -> EmailMessage:
    source_type, trust_label = (
        _stored_source_labels(row) if preserve_source_labels else ("stored_email", "email_evidence")
    )
    return EmailMessage(
        message_id=str(row.get("message_id") or ""),
        thread_id=str(row.get("thread_id") or "default"),
        sender=str(row.get("sender") or ""),
        subject=str(row.get("subject") or ""),
        received_at=str(row.get("received_at") or ""),
        body_text=str(row.get("body_text") or ""),
        attachment_texts=tuple(str(item) for item in row.get("attachment_texts") or ()),
        attachment_names=tuple(str(item) for item in row.get("attachment_names") or ()),
        source_type=source_type,
        trust_label=trust_label,
        labels=tuple(str(item) for item in row.get("labels") or ()),
        list_unsubscribe=str(row.get("list_unsubscribe") or ""),
    )


def _stored_source_labels(row: dict[str, Any]) -> tuple[str, str]:
    for fact in row.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        metadata = fact.get("metadata") if isinstance(fact.get("metadata"), dict) else {}
        source_type = str(fact.get("source_type") or metadata.get("source_type") or "")
        trust_label = str(fact.get("trust_label") or metadata.get("trust_label") or "")
        if source_type or trust_label:
            return source_type or "stored_email", trust_label or "email_evidence"
    return "stored_email", "email_evidence"


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
        labels=tuple(str(label) for label in item.get("labels") or ()),
        list_unsubscribe=str(item.get("list_unsubscribe") or ""),
    )
