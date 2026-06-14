"""Route handlers for the daily landing loop and readonly Gmail sync."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from ..daily import build_daily_landing_summary
from ..gmail_readiness import build_gmail_readiness
from ..gmail_sync import DEFAULT_DAILY_GMAIL_QUERY, run_gmail_readonly_sync
from ..gmail_sync_diagnostics import build_gmail_sync_diagnostics, record_gmail_sync_failure
from .helpers import query_int

if TYPE_CHECKING:  # pragma: no cover - typing only
    from urllib.parse import ParseResult

    from .app import Handler


def handle_daily_summary(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    h.send_json(
        build_daily_landing_summary(
            h.paths,
            task_limit=query_int(query, "task_limit", 12),
            calendar_limit=query_int(query, "calendar_limit", 20),
            actor="dashboard",
            record_audit=False,
            account_id=query.get("account", ["default"])[0],
            google_credentials_env=query.get("google_credentials_env", ["SENTINEL_GOOGLE_CREDENTIALS_JSON"])[0],
            google_token_env=query.get("google_token_env", ["SENTINEL_GOOGLE_TOKEN_JSON"])[0],
        )
    )


def handle_daily_run(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    h.send_json(
        build_daily_landing_summary(
            h.paths,
            task_limit=query_int(query, "task_limit", 12),
            calendar_limit=query_int(query, "calendar_limit", 20),
            actor="dashboard",
            record_audit=True,
            account_id=query.get("account", ["default"])[0],
            google_credentials_env=query.get("google_credentials_env", ["SENTINEL_GOOGLE_CREDENTIALS_JSON"])[0],
            google_token_env=query.get("google_token_env", ["SENTINEL_GOOGLE_TOKEN_JSON"])[0],
        )
    )


def handle_gmail_readiness(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    h.send_json(
        build_gmail_readiness(
            h.paths,
            account_id=query.get("account", ["default"])[0],
            credentials_env=query.get("google_credentials_env", ["SENTINEL_GOOGLE_CREDENTIALS_JSON"])[0],
            token_env=query.get("google_token_env", ["SENTINEL_GOOGLE_TOKEN_JSON"])[0],
        )
    )


def handle_gmail_sync_diagnostics(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    h.send_json(
        build_gmail_sync_diagnostics(
            h.paths,
            account_id=query.get("account", ["default"])[0],
            limit=query_int(query, "limit", 20),
        )
    )


def handle_gmail_sync(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    confirmed = query.get("confirm", ["0"])[0] in {"1", "true", "yes"}
    account_id = query.get("account", ["default"])[0]
    credentials_env = query.get("google_credentials_env", ["SENTINEL_GOOGLE_CREDENTIALS_JSON"])[0]
    token_env = query.get("google_token_env", ["SENTINEL_GOOGLE_TOKEN_JSON"])[0]
    gmail_query = query.get("query", [""])[0]
    since = query.get("since", [None])[0]
    limit = query_int(query, "limit", 50)
    task_limit = query_int(query, "task_limit", 12)
    calendar_limit = query_int(query, "calendar_limit", 20)
    if not confirmed:
        h.send_json(
            {
                "allowed": False,
                "requires_confirmation": True,
                "action": "gmail.readonly_sync",
                "reason": "Readonly Gmail sync requires an explicit user-triggered confirmation.",
                "side_effect": "gmail_readonly_plus_local_db_write",
                "external_network": False,
                "external_writes_performed": False,
                "next_action": {
                    "kind": "confirm_gmail_sync",
                    "label": "Run readonly Gmail sync",
                    "command": "/api/gmail/sync?confirm=1",
                    "side_effect": "gmail_readonly_plus_local_db_write",
                },
            }
        )
        return
    resolved_query = gmail_query or DEFAULT_DAILY_GMAIL_QUERY
    try:
        sync_summary = run_gmail_readonly_sync(
            h.paths,
            account_id=account_id,
            query=gmail_query,
            default_query=DEFAULT_DAILY_GMAIL_QUERY,
            since=since,
            limit=limit,
            credentials_env=credentials_env,
            token_env=token_env,
        )
        daily_summary = build_daily_landing_summary(
            h.paths,
            sync_summary=sync_summary,
            task_limit=task_limit,
            calendar_limit=calendar_limit,
            actor="dashboard",
            record_audit=False,
            account_id=account_id,
            google_credentials_env=credentials_env,
            google_token_env=token_env,
        )
        h.send_json(
            {
                "status": "ready",
                "allowed": True,
                "mode": "gmail_readonly_sync",
                "sync": daily_summary["sync"],
                "daily_summary": daily_summary,
                "external_network": True,
                "external_writes_performed": False,
            }
        )
    except Exception as error:  # noqa: BLE001 - failures captured as redacted diagnostics
        diagnostics = record_gmail_sync_failure(
            h.paths,
            error=error,
            account_id=account_id,
            command="api gmail sync",
            query=resolved_query,
            since=since or "",
            limit=limit,
            credentials_env=credentials_env,
            token_env=token_env,
            actor="dashboard",
        )
        h.send_json(
            {
                "status": "failed",
                "allowed": True,
                "error": "gmail_sync_failed",
                "diagnostics": diagnostics,
                "daily_summary": build_daily_landing_summary(
                    h.paths,
                    task_limit=task_limit,
                    calendar_limit=calendar_limit,
                    actor="dashboard",
                    record_audit=False,
                    account_id=account_id,
                    google_credentials_env=credentials_env,
                    google_token_env=token_env,
                ),
                "external_network": True,
                "external_writes_performed": False,
            }
        )
