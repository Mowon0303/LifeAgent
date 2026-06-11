from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .extract import find_messages
from .ingest import load_email_json
from .models import EmailMessage


class ConnectorUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class EmailSyncRequest:
    query: str = ""
    since: str = ""
    limit: int = 50


@dataclass(frozen=True)
class EmailSyncResult:
    connector: str
    source_type: str
    trust_label: str
    messages: tuple[EmailMessage, ...]
    warnings: tuple[str, ...] = ()
    cursor: str = ""
    account_id: str = "default"
    scopes: tuple[str, ...] = ()
    metadata: dict[str, Any] | None = None


class EmailConnector(Protocol):
    name: str
    source_type: str
    trust_label: str

    def search(self, request: EmailSyncRequest) -> EmailSyncResult:
        ...


class LocalJsonEmailConnector:
    name = "local_json"
    source_type = "email"
    trust_label = "email_imported"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def search(self, request: EmailSyncRequest) -> EmailSyncResult:
        messages = [
            _with_connector_labels(message, source_type=self.source_type, trust_label=self.trust_label)
            for message in load_email_json(self.path)
        ]
        if request.query:
            messages = find_messages(messages, request.query, limit=request.limit)
        else:
            messages = sorted(messages, key=lambda message: message.received_at, reverse=True)[: request.limit]
        return EmailSyncResult(
            connector=self.name,
            source_type=self.source_type,
            trust_label=self.trust_label,
            messages=tuple(messages),
            account_id="local",
        )


class GmailApiEmailConnector:
    name = "gmail_api"
    source_type = "gmail"
    trust_label = "email_provider_api"

    def __init__(self, client: Any | None = None) -> None:
        self.client = client

    def search(self, request: EmailSyncRequest) -> EmailSyncResult:
        if self.client is None:
            raise ConnectorUnavailable("Gmail connector requires an authenticated client.")
        raw_result = self.client.search_messages(query=request.query, since=request.since, limit=request.limit)
        if isinstance(raw_result, dict):
            raw_messages = raw_result.get("messages", [])
            cursor = str(raw_result.get("cursor") or "")
            metadata = {key: value for key, value in raw_result.items() if key not in {"messages", "cursor"}}
        else:
            raw_messages = raw_result
            cursor = ""
            metadata = {}
        messages = tuple(_gmail_message_from_dict(item) for item in raw_messages)
        return EmailSyncResult(
            connector=self.name,
            source_type=self.source_type,
            trust_label=self.trust_label,
            messages=messages,
            cursor=cursor,
            account_id=str(getattr(self.client, "account_id", "default")),
            scopes=tuple(getattr(self.client, "scopes", ())),
            metadata=metadata,
        )


def _with_connector_labels(message: EmailMessage, *, source_type: str, trust_label: str) -> EmailMessage:
    return EmailMessage(
        message_id=message.message_id,
        thread_id=message.thread_id,
        sender=message.sender,
        subject=message.subject,
        received_at=message.received_at,
        body_text=message.body_text,
        attachment_texts=message.attachment_texts,
        attachment_names=message.attachment_names,
        source_type=message.source_type or source_type,
        trust_label=message.trust_label if message.trust_label != "email_unverified" else trust_label,
    )


def _gmail_message_from_dict(item: dict[str, Any]) -> EmailMessage:
    return EmailMessage(
        message_id=str(item.get("message_id") or item.get("id") or ""),
        thread_id=str(item.get("thread_id") or item.get("thread") or ""),
        sender=str(item.get("sender") or item.get("from") or ""),
        subject=str(item.get("subject") or ""),
        received_at=str(item.get("received_at") or item.get("date") or ""),
        body_text=str(item.get("body_text") or item.get("body") or ""),
        attachment_texts=tuple(item.get("attachment_texts") or []),
        attachment_names=tuple(item.get("attachment_names") or []),
        source_type="gmail",
        trust_label="email_provider_api",
    )
