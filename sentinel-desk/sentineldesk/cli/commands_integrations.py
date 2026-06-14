"""Live/sandbox integration commands: readiness, verification, handoff, tokens."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .. import db
from ..calendar.models import DeadlineEvent
from ..config import ensure_dirs
from ..extract import utc_now
from ..gmail_readiness import build_gmail_readiness
from ..gmail_sync_diagnostics import build_gmail_sync_diagnostics
from ..integrations.google_oauth import normalize_google_scopes, write_google_oauth_token
from ..integrations.live_verification import (
    build_completion_audit,
    build_env_template,
    format_handoff_checklist,
    run_verification,
)
from ..reports import integration_package_path_for, write_integration_verification_package
from ..secrets import env_secret
from .common import paths_from_args, print_json


def cmd_integrations_check(args: argparse.Namespace) -> int:
    if args.package and args.no_persist:
        print_json({"error": "integrations check --package requires persistence; remove --no-persist"})
        return 1
    paths = paths_from_args(args)
    ensure_dirs(paths)
    report = run_verification(
        paths,
        suite=args.suite,
        account_id=args.account,
        google_credentials_env=args.google_credentials_env,
        google_token_env=args.google_token_env,
        apple_user_env=args.apple_user_env,
        apple_password_env=args.apple_password_env,
        persist=not args.no_persist,
    )
    payload = report.to_dict()
    if args.package:
        package_path = write_integration_verification_package(integration_package_path_for(payload, paths.artifacts), payload)
        payload["package_path"] = str(package_path)
        payload["package_privacy"] = "Package contains redacted integration verification evidence only."
    print_json(payload)
    return 1 if args.require_ready and report.status != "ready" else 0


def cmd_integrations_reports(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    db.init_db(paths)
    print_json(db.list_integration_verifications(paths, limit=args.limit))
    return 0


def cmd_integrations_gmail_readiness(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    print_json(
        build_gmail_readiness(
            paths,
            account_id=args.account,
            credentials_env=args.google_credentials_env,
            token_env=args.google_token_env,
        )
    )
    return 0


def cmd_integrations_gmail_sync_diagnostics(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    print_json(build_gmail_sync_diagnostics(paths, account_id=args.account, limit=args.limit))
    return 0


def cmd_integrations_completion_audit(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    audit = build_completion_audit(
        paths,
        account_id=args.account,
        google_credentials_env=args.google_credentials_env,
        google_token_env=args.google_token_env,
        apple_user_env=args.apple_user_env,
        apple_password_env=args.apple_password_env,
        source_release_path=args.source_release_path,
    )
    print_json(audit)
    return 1 if args.require_ready and not audit["ready"] else 0


def cmd_integrations_handoff(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    audit = build_completion_audit(
        paths,
        account_id=args.account,
        google_credentials_env=args.google_credentials_env,
        google_token_env=args.google_token_env,
        apple_user_env=args.apple_user_env,
        apple_password_env=args.apple_password_env,
        source_release_path=args.source_release_path,
    )
    checklist = format_handoff_checklist(audit)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(checklist, encoding="utf-8")
        print_json(
            {
                "status": "written",
                "ready": audit["ready"],
                "output_path": str(output_path),
                "privacy": "Handoff checklist contains redacted refs and commands only; it does not include secret values.",
            }
        )
    else:
        print(checklist)
    return 1 if args.require_ready and not audit["ready"] else 0


def cmd_integrations_package(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    db.init_db(paths)
    report = _load_integration_report(paths, args.verification_id)
    if not report:
        print_json({"error": "integration verification not found", "verification_id": args.verification_id})
        return 1
    output_path = Path(args.output) if args.output else integration_package_path_for(report, paths.artifacts)
    package_path = write_integration_verification_package(output_path, report)
    print_json(
        {
            "verification_id": report.get("verification_id"),
            "suite": report.get("suite"),
            "status": report.get("status"),
            "package_path": str(package_path),
            "privacy": "Package contains redacted integration verification evidence only.",
        }
    )
    return 0


def cmd_integrations_seed_calendar_draft(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    db.init_db(paths)
    timestamp = utc_now()
    event = DeadlineEvent(
        title=args.title,
        date_text=args.date,
        source_ids=(args.source_id,),
        severity=args.severity,
        confidence=args.confidence,
        evidence_uri=args.evidence_uri,
    )
    row_id = db.upsert_calendar_draft(
        paths,
        event=event,
        created_at=timestamp,
        updated_at=timestamp,
        sync_state="local_draft",
    )
    db.insert_audit_event(
        paths,
        action="integration.seed_calendar_draft",
        actor=args.actor,
        subject=event.event_id,
        capability="calendar_draft",
        side_effect="local_db_write",
        allowed=True,
        confirmation_id="",
        metadata={
            "title": event.title,
            "date_text": event.date_text,
            "source_ids": list(event.source_ids),
            "evidence_uri": event.evidence_uri,
            "purpose": "live_calendar_sync_verification",
        },
        created_at=timestamp,
    )
    print_json(
        {
            "row_id": row_id,
            "event_id": event.event_id,
            "title": event.title,
            "date_text": event.date_text,
            "source_ids": list(event.source_ids),
            "evidence_uri": event.evidence_uri,
            "sync_state": "local_draft",
            "external_write": False,
            "next_step": "Run calendar sync preview, then confirmed Google/Apple sync with explicit confirmation IDs.",
        }
    )
    return 0


def _load_integration_report(paths, verification_id: str) -> dict[str, object] | None:
    records = db.list_integration_verifications(paths, limit=1) if verification_id == "latest" else []
    record = records[0] if records else db.get_integration_verification(paths, verification_id)
    if not record:
        return None
    artifact_path = Path(str(record.get("artifact_path") or ""))
    if artifact_path.exists():
        try:
            return json.loads(artifact_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "verification_id": record.get("verification_id"),
        "suite": record.get("suite"),
        "status": record.get("status"),
        "checks": record.get("checks") or [],
        "artifact_path": record.get("artifact_path"),
        "created_at": record.get("created_at"),
    }


def cmd_integrations_env_template(args: argparse.Namespace) -> int:
    print_json(
        build_env_template(
            account_id=args.account,
            google_credentials_env=args.google_credentials_env,
            google_token_env=args.google_token_env,
            apple_user_env=args.apple_user_env,
            apple_password_env=args.apple_password_env,
        )
    )
    return 0


def cmd_integrations_google_token(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    output_path = Path(args.token_output) if args.token_output else paths.home / "secrets" / "google-token.json"
    result = write_google_oauth_token(
        credentials_ref=env_secret(args.credentials_env),
        output_path=output_path,
        token_env=args.token_env,
        scopes=normalize_google_scopes(args.scope),
        port=args.port,
        open_browser=not args.no_browser,
    )
    print_json(result.to_dict())
    return 0
