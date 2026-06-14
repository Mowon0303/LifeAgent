"""Calendar commands: sync drafts to ICS/Google/Apple, edit local drafts."""

from __future__ import annotations

import argparse
from pathlib import Path

from .. import db
from ..calendar.adapters import (
    AppleCalendarAdapter,
    GoogleCalendarAdapter,
    IcsFileCalendarAdapter,
    sync_calendar_draft,
)
from ..calendar.models import CalendarDraft
from ..calendar.source import events_from_calendar_rows
from ..config import ensure_dirs
from ..extract import utc_now
from ..integrations.apple_calendar import AppleCalendarClientFactory, AppleCalendarConfig
from ..integrations.google_workspace import CALENDAR_EVENTS_SCOPE, GoogleOAuthConfig, GoogleWorkspaceFactory
from ..secrets import env_secret
from .common import paths_from_args, print_json


def cmd_calendar_sync(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    db.init_db(paths)
    events = events_from_calendar_rows(db.list_calendar_drafts(paths, limit=args.limit), event_id=args.event_id)
    if not events:
        print_json({"error": "no calendar drafts found", "event_id": args.event_id or ""})
        return 1
    if args.destination in {"google", "apple"} and args.confirm and not args.confirmation_id:
        print_json({"error": "external calendar sync requires --confirmation-id"})
        return 1
    draft = CalendarDraft(events=tuple(events))
    adapter = _calendar_adapter_from_args(paths, args)
    result = sync_calendar_draft(
        paths,
        draft,
        adapter,
        confirmed=args.confirm,
        confirmation_id=args.confirmation_id if args.confirm else "",
        actor=args.actor,
    )
    if result.allowed:
        for event_id in result.event_ids:
            db.update_calendar_draft_sync_state(
                paths,
                event_id=event_id,
                sync_state=f"{args.destination}_synced",
                status="synced",
                updated_at=utc_now(),
            )
    print_json(result.__dict__)
    return 0 if result.allowed or not args.confirm else 1


def cmd_calendar_edit(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    db.init_db(paths)
    updated_at = utc_now()
    updated = db.update_calendar_draft(
        paths,
        event_id=args.event_id,
        title=args.title,
        date_text=args.date,
        severity=args.severity,
        status="draft",
        sync_state="local_draft",
        updated_at=updated_at,
    )
    if not updated:
        print_json({"error": "calendar draft not found", "event_id": args.event_id})
        return 1
    db.insert_audit_event(
        paths,
        action="calendar.edit",
        actor=args.actor,
        subject=args.event_id,
        capability="calendar_draft",
        side_effect="local_db_write",
        allowed=True,
        confirmation_id="",
        metadata={
            "title": updated.get("title"),
            "date_text": updated.get("date_text"),
            "severity": updated.get("severity"),
            "sync_state": updated.get("sync_state"),
            "external_write": False,
        },
        created_at=updated_at,
    )
    print_json({"updated": updated, "external_write": False})
    return 0


def _calendar_adapter_from_args(paths, args: argparse.Namespace):
    if args.destination == "ics":
        output_path = Path(args.output) if args.output else paths.artifacts / "calendar" / "lifeagent-deadlines.ics"
        return IcsFileCalendarAdapter(output_path)
    if args.destination == "google":
        client = None
        calendar_id = args.calendar_id or "primary"
        if args.confirm:
            config = GoogleOAuthConfig(
                credentials_json=env_secret(args.google_credentials_env),
                token_json=env_secret(args.google_token_env),
                scopes=(CALENDAR_EVENTS_SCOPE,),
                account_id=args.account,
            )
            client = GoogleWorkspaceFactory(config).calendar_client(calendar_id=calendar_id)
        return GoogleCalendarAdapter(client, calendar_id=calendar_id)
    if args.destination == "apple":
        client = None
        calendar_id = args.calendar_id or "default"
        if args.confirm:
            config = AppleCalendarConfig(
                username=env_secret(args.apple_user_env),
                app_password=env_secret(args.apple_password_env),
                account_id=args.account,
            )
            client = AppleCalendarClientFactory(config).calendar_client()
        return AppleCalendarAdapter(client, calendar_id=calendar_id)
    raise ValueError(f"Unsupported calendar destination: {args.destination}")
