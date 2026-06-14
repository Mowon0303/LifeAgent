from __future__ import annotations

import base64
import importlib
import json
from dataclasses import dataclass
from typing import Any

from sentineldesk.calendar.models import DeadlineEvent
from sentineldesk.secrets import SecretRef, SecretUnavailable, resolve_secret


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"


class GoogleIntegrationUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class GoogleOAuthConfig:
    credentials_json: SecretRef
    token_json: SecretRef
    scopes: tuple[str, ...]
    account_id: str = "default"

    def safe_summary(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "scopes": list(self.scopes),
            "credentials": self.credentials_json.redacted,
            "token": self.token_json.redacted,
        }


class GoogleWorkspaceFactory:
    def __init__(self, config: GoogleOAuthConfig) -> None:
        self.config = config

    def gmail_client(self) -> "GoogleGmailClient":
        service = _build_service("gmail", "v1", self.config)
        return GoogleGmailClient(service)

    def calendar_client(self, calendar_id: str = "primary") -> "GoogleCalendarClient":
        service = _build_service("calendar", "v3", self.config)
        return GoogleCalendarClient(service, calendar_id=calendar_id)


class GoogleGmailClient:
    def __init__(self, service: Any) -> None:
        self.service = service

    def search_messages(self, query: str, since: str, limit: int) -> dict[str, Any]:
        q = query
        if since and "after:" not in q:
            q = f"{q} after:{since}".strip()
        request = self.service.users().messages().list(userId="me", q=q, maxResults=limit)
        response = request.execute()
        messages = []
        for item in response.get("messages", []):
            detail = self.service.users().messages().get(userId="me", id=item["id"], format="full").execute()
            messages.append(_gmail_message_payload(detail))
        return {
            "messages": messages,
            "cursor": str(response.get("historyId") or response.get("nextPageToken") or ""),
            "raw_count": len(response.get("messages", [])),
        }


class GoogleCalendarClient:
    def __init__(self, service: Any, *, calendar_id: str = "primary") -> None:
        self.service = service
        self.calendar_id = calendar_id

    def create_event(self, calendar_id: str, event: DeadlineEvent) -> dict[str, Any]:
        target_calendar = calendar_id or self.calendar_id
        body = {
            "summary": event.title,
            "start": {"date": _date_text(event.date_text)},
            "end": {"date": _date_text(event.date_text)},
            "description": "Sources: " + ", ".join(event.source_ids),
            "transparency": "transparent",
        }
        return self.service.events().insert(calendarId=target_calendar, body=body).execute()


def _build_service(api_name: str, version: str, config: GoogleOAuthConfig) -> Any:
    discovery = _import("googleapiclient.discovery")
    credentials_cls = getattr(_import("google.oauth2.credentials"), "Credentials", None)
    if credentials_cls is None:
        raise GoogleIntegrationUnavailable("google.oauth2.credentials.Credentials is unavailable.")
    _load_secret_json(config.credentials_json)
    token_info = _load_secret_json(config.token_json)
    credentials = credentials_cls.from_authorized_user_info(token_info, scopes=list(config.scopes))
    return discovery.build(api_name, version, credentials=credentials, cache_discovery=False)


def _load_secret_json(ref: SecretRef) -> dict[str, Any]:
    raw = resolve_secret(ref)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            return json.loads(base64.b64decode(raw).decode("utf-8"))
        except Exception as exc:
            raise SecretUnavailable(f"Secret {ref.redacted} is not JSON or base64 JSON.") from exc


def _import(module_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise GoogleIntegrationUnavailable(f"Optional Google dependency missing: {module_name}") from exc


def _gmail_message_payload(detail: dict[str, Any]) -> dict[str, Any]:
    headers = {
        item.get("name", "").lower(): item.get("value", "")
        for item in detail.get("payload", {}).get("headers", [])
    }
    body_text = _decode_body(detail.get("payload", {}))
    return {
        "id": detail.get("id", ""),
        "thread_id": detail.get("threadId", ""),
        "from": headers.get("from", ""),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "body": body_text,
        # Already present in the format="full" response — no extra request or
        # scope. labelIds carry Gmail's own promotions/social/updates tabbing;
        # List-Unsubscribe marks bulk mail.
        "labels": list(detail.get("labelIds", []) or []),
        "list_unsubscribe": headers.get("list-unsubscribe", ""),
    }


def _decode_body(payload: dict[str, Any]) -> str:
    data = payload.get("body", {}).get("data")
    if data:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
    parts = payload.get("parts") or []
    if not parts:
        return ""
    # text/plain and text/html alternatives carry the SAME content; concatenating
    # both stored every value twice (a "$998" in the text and again in a
    # <td>$998</td>). Prefer the plain-text part; fall back to HTML (tags are
    # stripped downstream) only when no plain alternative exists.
    plain = [part for part in parts if str(part.get("mimeType") or "").startswith("text/plain")]
    html = [part for part in parts if str(part.get("mimeType") or "").startswith("text/html")]
    chosen = plain or html or parts
    return "\n".join(_decode_body(part) for part in chosen if part)


def _date_text(value: str) -> str:
    return value if value else "1970-01-01"
