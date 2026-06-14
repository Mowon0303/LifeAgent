"""Email-evidence commands: ask, email scan/sync/reprocess, daily landing loop."""

from __future__ import annotations

import argparse

from .. import db
from ..agent.embeddings import embedder_for
from ..agent.model import load_model_provider
from ..agent.rag_index import index_emails
from ..agent.tools import default_tool_registry
from ..agent.workflow import answer_with_workflow
from ..config import Paths, ensure_dirs
from ..daily import build_daily_landing_summary
from ..email.connectors import EmailSyncRequest, LocalJsonEmailConnector
from ..email.ingest import (
    ingest_messages,
    load_email_json,
    reprocess_stored_messages,
    stored_email_messages,
)
from ..email.models import EmailMessage
from ..gmail_sync import DEFAULT_DAILY_GMAIL_QUERY, run_gmail_readonly_sync
from ..gmail_sync_diagnostics import record_gmail_sync_failure
from .common import paths_from_args, print_json


def load_email_messages(path: str) -> list[EmailMessage]:
    return load_email_json(path)


def cmd_ask(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    messages = load_email_messages(args.email_json) if args.email_json else stored_email_messages(paths)
    answer = answer_with_workflow(args.question, provider=load_model_provider(paths), messages=messages, registry=default_tool_registry(paths), paths=paths)
    print_json(
        {
            "intent": answer.intent.value,
            "answer": answer.answer,
            "confidence": answer.confidence,
            "uncertain": answer.uncertain,
            "requires_confirmation": answer.requires_confirmation,
            "tool_calls": list(answer.tool_calls),
            "citations": [citation.__dict__ for citation in answer.citations],
            "metadata": answer.metadata,
        }
    )
    return 0


def cmd_email_scan(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    connector = LocalJsonEmailConnector(args.json)
    messages = list(connector.search(EmailSyncRequest(query=args.query or "", limit=args.limit)).messages)
    print_json(ingest_messages(paths, messages))
    return 0


def cmd_email_sync_gmail(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    db.init_db(paths)
    query = args.query or ""
    state = db.get_connector_state(paths, connector="gmail_api", account_id=args.account)
    since = args.since if args.since is not None else str((state or {}).get("cursor") or "")
    try:
        result = run_gmail_readonly_sync(
            paths,
            account_id=args.account,
            query=query,
            since=args.since,
            limit=args.limit,
            credentials_env=args.credentials_env,
            token_env=args.token_env,
        )
    except Exception as error:
        diagnostics = record_gmail_sync_failure(
            paths,
            error=error,
            account_id=args.account,
            command="email sync-gmail",
            query=query,
            since=since,
            limit=args.limit,
            credentials_env=args.credentials_env,
            token_env=args.token_env,
            actor="user",
        )
        print_json({"error": "gmail_sync_failed", "diagnostics": diagnostics})
        return 1
    print_json({"oauth": result["oauth"], "sync": {key: value for key, value in result.items() if key != "oauth"}})
    return 0


def cmd_email_reprocess(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    print_json(
        reprocess_stored_messages(
            paths,
            limit=args.limit,
            rebuild_calendar_drafts=not args.no_calendar_drafts,
        )
    )
    return 0


def cmd_daily_run(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    db.init_db(paths)
    if args.email_json and args.sync_gmail:
        print_json({"error": "Use either --email-json or --sync-gmail, not both."})
        return 1
    sync_summary: dict[str, object] | None = None
    if args.email_json:
        connector = LocalJsonEmailConnector(args.email_json)
        messages = list(connector.search(EmailSyncRequest(query=args.query or "", limit=args.limit)).messages)
        ingest_summary = ingest_messages(paths, messages)
        sync_summary = {
            "mode": "local_json",
            "external_network": False,
            "source": str(args.email_json),
            "query": args.query or "",
            **ingest_summary,
        }
    elif args.sync_gmail:
        state = db.get_connector_state(paths, connector="gmail_api", account_id=args.account)
        since = args.since if args.since is not None else str((state or {}).get("cursor") or "")
        query = args.query or DEFAULT_DAILY_GMAIL_QUERY
        try:
            sync_summary = run_gmail_readonly_sync(
                paths,
                account_id=args.account,
                query=args.query or "",
                default_query=DEFAULT_DAILY_GMAIL_QUERY,
                since=args.since,
                limit=args.limit,
                credentials_env=args.credentials_env,
                token_env=args.token_env,
            )
        except Exception as error:
            diagnostics = record_gmail_sync_failure(
                paths,
                error=error,
                account_id=args.account,
                command="daily run --sync-gmail",
                query=query,
                since=since,
                limit=args.limit,
                credentials_env=args.credentials_env,
                token_env=args.token_env,
                actor=args.actor,
            )
            print_json(
                {
                    "error": "gmail_sync_failed",
                    "diagnostics": diagnostics,
                    "daily_summary": build_daily_landing_summary(
                        paths,
                        task_limit=args.task_limit,
                        calendar_limit=args.calendar_limit,
                        actor=args.actor,
                        record_audit=False,
                        account_id=args.account,
                        google_credentials_env=args.credentials_env,
                        google_token_env=args.token_env,
                    ),
                }
            )
            return 1
        sync_summary = {**sync_summary, "oauth": _redacted_daily_oauth_summary(sync_summary.get("oauth", {}))}
    if args.reprocess_stored:
        reprocess_summary = reprocess_stored_messages(
            paths,
            limit=args.reprocess_limit,
            rebuild_calendar_drafts=not args.no_calendar_drafts,
        )
        if sync_summary:
            sync_summary = {**sync_summary, "reprocess": reprocess_summary}
        else:
            sync_summary = reprocess_summary
    embed_summary = _daily_embed_step(paths, force=getattr(args, "embed", False))
    if embed_summary is not None:
        sync_summary = {**(sync_summary or {}), "embed": embed_summary}
    print_json(
        build_daily_landing_summary(
            paths,
            sync_summary=sync_summary,
            task_limit=args.task_limit,
            calendar_limit=args.calendar_limit,
            actor=args.actor,
            account_id=args.account,
            google_credentials_env=args.credentials_env,
            google_token_env=args.token_env,
        )
    )
    return 0


def _daily_embed_step(paths: Paths, *, force: bool) -> dict[str, object] | None:
    """Incrementally embed newly synced mail into the RAG store when --embed is
    passed or [model] auto_embed is on. Already-embedded mail is skipped, so
    this is cheap on a daily run."""
    provider = load_model_provider(paths)
    if not (force or provider.auto_embed):
        return None
    embedder = embedder_for(provider)
    count = index_emails(paths, embedder=embedder, skip_indexed=True)
    return {"emails_embedded": count, "embedder": embedder.name}


def _redacted_daily_oauth_summary(summary: dict[str, object]) -> dict[str, object]:
    safe = dict(summary)
    if safe.get("account_id"):
        safe["account_id"] = "[REDACTED_CONNECTOR_METADATA]"
    return safe
