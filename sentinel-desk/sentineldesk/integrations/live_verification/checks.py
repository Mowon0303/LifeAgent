"""Suite check builders and the secret/format/module check primitives.

This module holds the actual readiness probes (Gmail, Calendar, LangGraph,
sandbox) plus the sandbox clients used to exercise the connector/adapter paths.
``_module_check`` is the only optional-dependency probe and uses
``importlib.util.find_spec``.
"""

from __future__ import annotations

import base64
import importlib.util
import json
from typing import Any

from sentineldesk import db
from sentineldesk.agent.model import load_model_provider
from sentineldesk.agent.workflow import build_langgraph_workflow, runtime_for
from sentineldesk.calendar.adapters import AppleCalendarAdapter, GoogleCalendarAdapter, sync_calendar_draft
from sentineldesk.calendar.models import CalendarDraft, DeadlineEvent
from sentineldesk.config import Paths
from sentineldesk.email.connectors import EmailSyncRequest, GmailApiEmailConnector
from sentineldesk.email.ingest import sync_connector
from sentineldesk.integrations.apple_calendar import APPLE_CALDAV_URL
from sentineldesk.integrations.google_workspace import CALENDAR_EVENTS_SCOPE, GMAIL_READONLY_SCOPE
from sentineldesk.secrets import SecretUnavailable, env_secret, resolve_secret, secret_status

from .models import VerificationCheck


def _gmail_checks(paths: Paths, account_id: str, credentials_env: str, token_env: str) -> list[VerificationCheck]:
    state = db.get_connector_state(paths, connector="gmail_api", account_id=account_id)
    return [
        _secret_check("gmail.credentials", credentials_env),
        _google_credentials_format_check("gmail.credentials_format", credentials_env),
        _secret_check("gmail.token", token_env),
        _google_token_format_check("gmail.token_format", token_env),
        _token_scope_check("gmail.token_scope", token_env, (GMAIL_READONLY_SCOPE,)),
        _module_check("gmail.googleapiclient", "googleapiclient.discovery"),
        _module_check("gmail.oauth_credentials", "google.oauth2.credentials"),
        _module_check("gmail.oauth_flow", "google_auth_oauthlib.flow"),
        VerificationCheck(
            name="gmail.scope",
            status="ready",
            detail="Gmail readonly scope is configured.",
            metadata={"scope": GMAIL_READONLY_SCOPE},
        ),
        VerificationCheck(
            name="gmail.cursor",
            status="ready" if state and state.get("cursor") else "missing",
            detail="Stored Gmail cursor found." if state and state.get("cursor") else "No stored Gmail cursor yet.",
            metadata={"account_id": account_id, "connector": "gmail_api", "has_cursor": bool(state and state.get("cursor"))},
        ),
    ]


def _calendar_checks(
    paths: Paths,
    account_id: str,
    google_credentials_env: str,
    google_token_env: str,
    apple_user_env: str,
    apple_password_env: str,
) -> list[VerificationCheck]:
    return [
        _secret_check("google_calendar.credentials", google_credentials_env),
        _google_credentials_format_check("google_calendar.credentials_format", google_credentials_env),
        _secret_check("google_calendar.token", google_token_env),
        _google_token_format_check("google_calendar.token_format", google_token_env),
        _token_scope_check("google_calendar.token_scope", google_token_env, (CALENDAR_EVENTS_SCOPE,)),
        _module_check("google_calendar.googleapiclient", "googleapiclient.discovery"),
        _module_check("google_calendar.oauth_flow", "google_auth_oauthlib.flow"),
        VerificationCheck(
            name="google_calendar.scope",
            status="ready",
            detail="Google Calendar events scope is configured.",
            metadata={"scope": CALENDAR_EVENTS_SCOPE, "account_id": account_id},
        ),
        _calendar_sync_evidence_check(paths, "google_calendar.sync_evidence", "google_calendar"),
        _secret_check("apple_calendar.username", apple_user_env),
        _apple_username_format_check("apple_calendar.username_format", apple_user_env),
        _secret_check("apple_calendar.app_password", apple_password_env),
        _apple_app_password_format_check("apple_calendar.app_password_format", apple_password_env),
        _module_check("apple_calendar.caldav", "caldav"),
        VerificationCheck(
            name="apple_calendar.endpoint",
            status="ready",
            detail="Apple CalDAV endpoint is configured.",
            metadata={"caldav_url": APPLE_CALDAV_URL},
        ),
        _calendar_sync_evidence_check(paths, "apple_calendar.sync_evidence", "apple_calendar"),
    ]


def _langgraph_checks(paths: Paths) -> list[VerificationCheck]:
    provider = load_model_provider(paths)
    runtime = runtime_for(provider)
    runnable = build_langgraph_workflow() if runtime.engine == "langgraph" else None
    return [
        _module_check("langgraph.module", "langgraph.graph"),
        VerificationCheck(
            name="langgraph.runtime",
            status="ready" if runtime.engine == "langgraph" and runnable is not None else "missing",
            detail="LangGraph workflow is buildable." if runnable is not None else "LangGraph is not installed or workflow could not be built.",
            metadata={
                "engine": runtime.engine,
                "reason": runtime.reason,
                "provider": provider.provider,
                "model": provider.model,
            },
        ),
    ]


def _sandbox_checks(paths: Paths, account_id: str, timestamp: str) -> list[VerificationCheck]:
    sandbox_id = _compact_id(timestamp)
    gmail_client = _SandboxGmailClient(account_id=account_id, message_id=f"sandbox-gmail-{sandbox_id}")
    gmail_summary = sync_connector(
        paths,
        GmailApiEmailConnector(gmail_client),
        EmailSyncRequest(query="deadline", since="sandbox-history-0", limit=5),
        account_id=account_id,
        ingested_at=timestamp,
    )

    event = DeadlineEvent(
        title="Sandbox deadline",
        date_text="2026-07-15",
        source_ids=(f"gmail:{gmail_client.message_id}",),
        evidence_uri=f"gmail:{gmail_client.message_id}",
    )
    draft = CalendarDraft((event,))

    google_client = _SandboxCalendarClient("sandbox-google-event")
    google_adapter = GoogleCalendarAdapter(google_client)
    google_blocked = sync_calendar_draft(paths, draft, google_adapter, confirmed=False, actor="sandbox")
    google_allowed = sync_calendar_draft(
        paths,
        draft,
        google_adapter,
        confirmed=True,
        confirmation_id=f"sandbox-google-{sandbox_id}",
        actor="sandbox",
    )

    apple_client = _SandboxCalendarClient("sandbox-apple-event")
    apple_adapter = AppleCalendarAdapter(apple_client, calendar_id="sandbox-icloud")
    apple_blocked = sync_calendar_draft(paths, draft, apple_adapter, confirmed=False, actor="sandbox")
    apple_allowed = sync_calendar_draft(
        paths,
        draft,
        apple_adapter,
        confirmed=True,
        confirmation_id=f"sandbox-apple-{sandbox_id}",
        actor="sandbox",
    )

    approvals = db.list_approval_records(paths, limit=20)
    return [
        VerificationCheck(
            name="sandbox.gmail_sync",
            status="ready" if gmail_summary["cursor_saved"] and gmail_summary["messages_persisted"] == 1 else "missing",
            detail="Sandbox Gmail connector sync exercised cursor persistence, email ingest, and deadline extraction.",
            metadata={
                "connector": gmail_summary["connector"],
                "account_id": gmail_summary["account_id"],
                "cursor_saved": gmail_summary["cursor_saved"],
                "scopes": gmail_summary["scopes"],
                "messages_persisted": gmail_summary["messages_persisted"],
                "facts_extracted": gmail_summary["facts_extracted"],
                "deadline_events_drafted": gmail_summary["deadline_events_drafted"],
            },
        ),
        VerificationCheck(
            name="sandbox.google_calendar_confirmation",
            status="ready" if (not google_blocked.allowed and google_allowed.allowed and google_client.created) else "missing",
            detail="Sandbox Google Calendar adapter exercised blocked write, confirmed write, audit, and approval record paths.",
            metadata={
                "blocked_reason": google_blocked.reason,
                "allowed": google_allowed.allowed,
                "external_ids": list(google_allowed.external_ids),
                "created_count": len(google_client.created),
                "confirmation_id": f"sandbox-google-{sandbox_id}",
            },
        ),
        VerificationCheck(
            name="sandbox.apple_calendar_confirmation",
            status="ready" if (not apple_blocked.allowed and apple_allowed.allowed and apple_client.created) else "missing",
            detail="Sandbox Apple Calendar adapter exercised blocked write, confirmed write, audit, and approval record paths.",
            metadata={
                "blocked_reason": apple_blocked.reason,
                "allowed": apple_allowed.allowed,
                "external_ids": list(apple_allowed.external_ids),
                "created_count": len(apple_client.created),
                "confirmation_id": f"sandbox-apple-{sandbox_id}",
            },
        ),
        VerificationCheck(
            name="sandbox.approval_records",
            status="ready" if len([item for item in approvals if str(item.get("confirmation_id", "")).startswith("sandbox-")]) >= 2 else "missing",
            detail="Sandbox confirmed calendar writes created durable approval records.",
            metadata={
                "sandbox_approval_count": len([item for item in approvals if str(item.get("confirmation_id", "")).startswith("sandbox-")]),
                "approval_actions": [item.get("action") for item in approvals[:5]],
            },
        ),
    ]


def _secret_check(name: str, env_name: str) -> VerificationCheck:
    status = secret_status(env_secret(env_name))
    return VerificationCheck(
        name=name,
        status="ready" if status["available"] else "missing",
        detail=f"Environment secret {env_name} is {'available' if status['available'] else 'missing'}.",
        metadata=status,
    )


def _google_credentials_format_check(name: str, env_name: str) -> VerificationCheck:
    ref = env_secret(env_name)
    status = secret_status(ref)
    try:
        info = _load_secret_json(ref)
    except SecretUnavailable:
        return VerificationCheck(
            name=name,
            status="missing" if not status["available"] else "invalid",
            detail=(
                f"Google OAuth credentials JSON {env_name} is missing."
                if not status["available"]
                else f"Google OAuth credentials JSON {env_name} is not valid JSON or base64 JSON."
            ),
            metadata={"credentials": ref.redacted, "available": status["available"], "json_parseable": False},
        )
    client_type = "installed" if isinstance(info.get("installed"), dict) else "web" if isinstance(info.get("web"), dict) else ""
    client = info.get(client_type) if client_type else {}
    required_fields = ["client_id", "auth_uri", "token_uri"]
    missing_fields = [field for field in required_fields if not isinstance(client, dict) or not client.get(field)]
    return VerificationCheck(
        name=name,
        status="ready" if client_type and not missing_fields else "invalid",
        detail=(
            "Google OAuth credentials JSON has a supported client config."
            if client_type and not missing_fields
            else "Google OAuth credentials JSON must contain an installed or web client with required OAuth fields."
        ),
        metadata={
            "credentials": ref.redacted,
            "available": True,
            "json_parseable": True,
            "client_type": client_type,
            "missing_fields": missing_fields,
        },
    )


def _google_token_format_check(name: str, token_env: str) -> VerificationCheck:
    ref = env_secret(token_env)
    status = secret_status(ref)
    try:
        token_info = _load_secret_json(ref)
    except SecretUnavailable:
        return VerificationCheck(
            name=name,
            status="missing" if not status["available"] else "invalid",
            detail=(
                f"Google authorized token JSON {token_env} is missing."
                if not status["available"]
                else f"Google authorized token JSON {token_env} is not valid JSON or base64 JSON."
            ),
            metadata={"token": ref.redacted, "available": status["available"], "json_parseable": False},
        )
    has_access_token = bool(token_info.get("token") or token_info.get("access_token"))
    required_fields = ["refresh_token", "token_uri", "client_id", "client_secret"]
    missing_fields = [field for field in required_fields if not token_info.get(field)]
    if not has_access_token:
        missing_fields.insert(0, "token")
    return VerificationCheck(
        name=name,
        status="ready" if not missing_fields else "invalid",
        detail=(
            "Google authorized token JSON has the fields needed for API clients."
            if not missing_fields
            else "Google authorized token JSON is missing one or more required fields."
        ),
        metadata={
            "token": ref.redacted,
            "available": True,
            "json_parseable": True,
            "missing_fields": missing_fields,
            "has_scope_metadata": bool(_extract_token_scopes(token_info)),
        },
    )


def _apple_username_format_check(name: str, user_env: str) -> VerificationCheck:
    ref = env_secret(user_env)
    status = secret_status(ref)
    try:
        raw = resolve_secret(ref)
    except SecretUnavailable:
        return VerificationCheck(
            name=name,
            status="missing",
            detail=f"Apple Calendar username {user_env} is missing.",
            metadata={"username": ref.redacted, "available": status["available"], "contains_at": False},
        )
    stripped = raw.strip()
    contains_whitespace = stripped != raw or any(char.isspace() for char in stripped)
    local_part, separator, domain_part = stripped.partition("@")
    contains_at = bool(separator)
    domain_has_dot = "." in domain_part
    valid = bool(local_part and domain_part and contains_at and domain_has_dot and not contains_whitespace)
    return VerificationCheck(
        name=name,
        status="ready" if valid else "invalid",
        detail=(
            "Apple Calendar username looks like an Apple ID email address."
            if valid
            else "Apple Calendar username should be an Apple ID email address without whitespace."
        ),
        metadata={
            "username": ref.redacted,
            "available": True,
            "contains_at": contains_at,
            "domain_has_dot": domain_has_dot,
            "contains_whitespace": contains_whitespace,
        },
    )


def _apple_app_password_format_check(name: str, password_env: str) -> VerificationCheck:
    ref = env_secret(password_env)
    status = secret_status(ref)
    try:
        raw = resolve_secret(ref)
    except SecretUnavailable:
        return VerificationCheck(
            name=name,
            status="missing",
            detail=f"Apple app-specific password {password_env} is missing.",
            metadata={"app_password": ref.redacted, "available": status["available"], "normalized_length": 0},
        )
    stripped = raw.strip()
    contains_whitespace = stripped != raw or any(char.isspace() for char in stripped)
    groups = stripped.split("-")
    dashed_format = len(groups) == 4 and all(len(group) == 4 and group.isalnum() for group in groups)
    compact_format = len(stripped) == 16 and stripped.isalnum()
    normalized_length = len(stripped.replace("-", ""))
    valid = not contains_whitespace and (dashed_format or compact_format)
    return VerificationCheck(
        name=name,
        status="ready" if valid else "invalid",
        detail=(
            "Apple app-specific password has a compatible local format."
            if valid
            else "Apple app-specific password should be four 4-character groups or a compact 16-character value without whitespace."
        ),
        metadata={
            "app_password": ref.redacted,
            "available": True,
            "normalized_length": normalized_length,
            "dash_group_count": len(groups) if "-" in stripped else 0,
            "dashed_format": dashed_format,
            "compact_format": compact_format,
            "contains_whitespace": contains_whitespace,
        },
    )


def _token_scope_check(name: str, token_env: str, required_scopes: tuple[str, ...]) -> VerificationCheck:
    ref = env_secret(token_env)
    try:
        token_info = _load_secret_json(ref)
    except SecretUnavailable:
        return VerificationCheck(
            name=name,
            status="missing",
            detail=f"Google token scope check could not read {token_env}.",
            metadata={"token": ref.redacted, "required_scopes": list(required_scopes), "scopes_present": [], "missing_scopes": list(required_scopes)},
        )
    scopes = _extract_token_scopes(token_info)
    missing = [scope for scope in required_scopes if scope not in scopes]
    return VerificationCheck(
        name=name,
        status="ready" if not missing else "missing",
        detail="Google token includes required OAuth scope." if not missing else "Google token is missing one or more required OAuth scopes.",
        metadata={
            "token": ref.redacted,
            "required_scopes": list(required_scopes),
            "scopes_present": scopes,
            "missing_scopes": missing,
            "token_json_parseable": True,
        },
    )


def _load_secret_json(ref: Any) -> dict[str, Any]:
    raw = resolve_secret(ref)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        try:
            parsed = json.loads(base64.b64decode(raw).decode("utf-8"))
        except Exception as exc:
            raise SecretUnavailable(f"Secret {ref.redacted} is not JSON or base64 JSON.") from exc
    if not isinstance(parsed, dict):
        raise SecretUnavailable(f"Secret {ref.redacted} must be a JSON object.")
    return parsed


def _extract_token_scopes(token_info: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("scopes", "scope", "granted_scopes", "grantedScopes"):
        value = token_info.get(key)
        if isinstance(value, str):
            values.extend(item.strip() for chunk in value.split(",") for item in chunk.split() if item.strip())
        elif isinstance(value, (list, tuple)):
            values.extend(str(item).strip() for item in value if str(item).strip())
    return list(dict.fromkeys(values))


def _calendar_sync_evidence_check(paths: Paths, name: str, subject: str) -> VerificationCheck:
    approvals = [
        item
        for item in db.list_approval_records(paths, limit=200)
        if item.get("action") == "calendar.sync"
        and item.get("subject") == subject
        and item.get("side_effect") == "external_calendar_write"
        and item.get("actor") != "sandbox"
    ]
    latest = approvals[0] if approvals else {}
    metadata = {
        "subject": subject,
        "has_approval": bool(approvals),
        "approval_count": len(approvals),
        "latest_confirmation_id": latest.get("confirmation_id", ""),
        "latest_status": latest.get("status", ""),
        "latest_created_at": latest.get("created_at", ""),
        "external_ids": (latest.get("metadata") or {}).get("external_ids", []) if latest else [],
        "created_external_ids": (latest.get("metadata") or {}).get("created_external_ids", []) if latest else [],
        "updated_external_ids": (latest.get("metadata") or {}).get("updated_external_ids", []) if latest else [],
    }
    return VerificationCheck(
        name=name,
        status="ready" if approvals else "missing",
        detail=f"Confirmed {subject} sync evidence found." if approvals else f"No confirmed {subject} sync evidence found yet.",
        metadata=metadata,
    )


def _module_check(name: str, module_name: str) -> VerificationCheck:
    try:
        available = importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:
        available = False
    return VerificationCheck(
        name=name,
        status="ready" if available else "missing",
        detail=f"Optional module {module_name} is {'available' if available else 'missing'}.",
        metadata={"module": module_name, "available": available},
    )


def _compact_id(timestamp: str) -> str:
    compact = "".join(ch for ch in timestamp if ch.isalnum())
    return compact or "sandbox"


class _SandboxGmailClient:
    scopes = (GMAIL_READONLY_SCOPE,)

    def __init__(self, *, account_id: str, message_id: str) -> None:
        self.account_id = account_id
        self.message_id = message_id

    def search_messages(self, query: str, since: str, limit: int) -> dict[str, object]:
        return {
            "cursor": f"sandbox-history-{self.message_id}",
            "raw_count": 1,
            "query": query,
            "since": since,
            "messages": [
                {
                    "id": self.message_id,
                    "thread_id": "sandbox-thread",
                    "from": "sandbox@example.com",
                    "subject": "Sandbox deadline",
                    "date": "2026-06-10",
                    "body": "Submit the sandbox form by July 15, 2026.",
                }
            ][:limit],
        }


class _SandboxCalendarClient:
    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        self.created: list[dict[str, object]] = []

    def create_event(self, calendar_id: str, event: DeadlineEvent) -> dict[str, str]:
        self.created.append({"calendar_id": calendar_id, "event_id": event.event_id})
        return {"id": self.event_id}
