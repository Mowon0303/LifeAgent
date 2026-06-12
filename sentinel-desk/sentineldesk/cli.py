from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, db
from .agent.model import load_model_provider
from .agent.providers import adapter_status_dict
from .agent.rag_index import index_file, search_index
from .agent.tools import default_tool_registry
from .agent.workflow import answer_with_workflow
from .calendar.adapters import AppleCalendarAdapter, GoogleCalendarAdapter, IcsFileCalendarAdapter, sync_calendar_draft
from .calendar.models import CalendarDraft, DeadlineEvent
from .calendar.source import events_from_calendar_rows
from .email.models import EmailMessage
from .email.connectors import EmailSyncRequest, GmailApiEmailConnector, LocalJsonEmailConnector
from .email.ingest import (
    ingest_messages,
    load_email_json,
    reprocess_stored_messages,
    stored_email_messages,
    sync_connector,
)
from .evals.email_extract import evaluate_golden_path, render_markdown_report, render_text_summary
from .integrations.apple_calendar import AppleCalendarClientFactory, AppleCalendarConfig
from .integrations.google_oauth import normalize_google_scopes, write_google_oauth_token
from .integrations.google_workspace import CALENDAR_EVENTS_SCOPE, GMAIL_READONLY_SCOPE, GoogleOAuthConfig, GoogleWorkspaceFactory
from .integrations.live_verification import build_completion_audit, build_env_template, format_handoff_checklist, run_verification
from .chrome import launch as launch_chrome
from .config import ensure_config, ensure_dirs, file_url, get_paths, project_root, seed_demo_fixtures
from .daily import build_daily_landing_summary
from .extract import utc_now
from .monitor import run_all
from .plantracker import format_plan_summary, summarize_plan
from .privacy import audit_project_tree, audit_redacted_artifacts, write_release_package
from .retention import plan_purge, purge, result_to_dict
from .reports import (
    integration_package_path_for,
    package_path_for,
    redact_data,
    write_evidence_package,
    write_integration_verification_package,
)
from .scenarios import apply_scenario, list_scenarios
from .server import serve
from .secrets import env_secret
from .tasks import list_tasks, review_task


def print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def paths_from_args(args: argparse.Namespace):
    return get_paths(getattr(args, "home", None))


def cmd_init(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    created = ensure_config(paths)
    db.init_db(paths)
    copied = seed_demo_fixtures(paths)
    print(f"SentinelDesk initialized at {paths.home}")
    print(f"Config: {paths.config} ({'created' if created else 'already existed'})")
    print(f"Database: {paths.database}")
    print(f"Demo fixtures copied: {copied}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    checks = []
    checks.append({"name": "home", "ok": paths.home.exists(), "detail": str(paths.home)})
    checks.append({"name": "config", "ok": paths.config.exists(), "detail": str(paths.config)})
    checks.append({"name": "database", "ok": paths.database.exists(), "detail": str(paths.database)})
    checks.append({"name": "artifacts_writable", "ok": paths.artifacts.exists() and paths.artifacts.is_dir(), "detail": str(paths.artifacts)})
    checks.append({"name": "chrome_profile", "ok": str(paths.chrome_profile).startswith(str(paths.home)), "detail": str(paths.chrome_profile)})
    print_json(checks)
    return 0 if all(item["ok"] for item in checks) else 1


def cmd_demo_seed(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    ensure_config(paths)
    db.init_db(paths)
    copied = seed_demo_fixtures(paths)
    apply_scenario(paths, "opt_baseline")
    apply_scenario(paths, "appointment_baseline")
    apply_scenario(paths, "lease_baseline")
    print(f"Seeded {copied} fixture files and 3 demo targets.")
    return 0


def cmd_demo_scenarios(args: argparse.Namespace) -> int:
    print_json(list_scenarios(kind=args.kind))
    return 0


def cmd_demo_apply(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    ensure_config(paths)
    db.init_db(paths)
    target = apply_scenario(paths, args.scenario, target_name=args.target_name)
    print_json({"target": target})
    if args.run:
        print_json({"runs": run_all(paths, name=target["name"])})
    return 0


def cmd_demo_record_prep(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    ensure_config(paths)
    db.init_db(paths)
    copied = seed_demo_fixtures(paths)
    sample_emails_path = project_root() / "fixtures" / "ui" / "sample_emails.json"

    apply_scenario(paths, "opt_baseline")
    apply_scenario(paths, "appointment_baseline")
    apply_scenario(paths, "lease_baseline")
    baseline_runs = run_all(paths)
    critical_target = apply_scenario(paths, "opt_action_required")
    critical_run = run_all(paths, name=critical_target["name"])[0]
    uncertain_target = apply_scenario(paths, "opt_session_expired")
    uncertain_run = run_all(paths, name=uncertain_target["name"])[0]
    email_summary = ingest_messages(
        paths,
        load_email_json(sample_emails_path),
        ingested_at="2026-06-25T12:00:00+00:00",
    )
    calendar_drafts = db.list_calendar_drafts(paths, limit=100)
    tasks = list_tasks(paths, limit=100)

    package_paths: dict[str, str] = {}
    for label, run in [("critical", critical_run), ("uncertain", uncertain_run)]:
        evidence_path = Path(run["evidence"]["path"])
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        package_paths[label] = str(write_evidence_package(package_path_for(evidence_path), evidence))

    runs = db.list_runs(paths, limit=20)
    alerts = db.list_alerts(paths, limit=20)
    print_json(
        {
            "home": str(paths.home),
            "fixtures_copied": copied,
            "dashboard_url": f"http://127.0.0.1:{args.port}/",
            "calendar_dashboard_url": f"http://127.0.0.1:{args.port}/",
            "ops_dashboard_url": f"http://127.0.0.1:{args.port}/ops",
            "serve_command": f"python3 -m sentineldesk --home {paths.home} serve --port {args.port}",
            "run_count": len(runs),
            "alert_count": len(alerts),
            "email_fixture": "fixtures/ui/sample_emails.json",
            "email_messages_persisted": email_summary["messages_persisted"],
            "email_facts_extracted": email_summary["facts_extracted"],
            "calendar_draft_count": len(calendar_drafts),
            "task_count": len(tasks),
            "baseline_run_ids": [run["run_id"] for run in baseline_runs],
            "critical_run_id": critical_run["run_id"],
            "uncertain_run_id": uncertain_run["run_id"],
            "critical_report": critical_run["evidence"]["report_path"],
            "uncertain_report": uncertain_run["evidence"]["report_path"],
            "packages": package_paths,
            "expected_states": ["email_calendar", "baseline", "critical", "uncertain"],
            "privacy_check": "Open redacted evidence/report/package outputs and confirm there are no real URLs, file:// URLs, local paths, screenshots, cookies, or databases.",
        }
    )
    return 0


def cmd_targets(args: argparse.Namespace) -> int:
    print_json(db.list_targets(paths_from_args(args)))
    return 0


def cmd_watch_add(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    db.init_db(paths)
    target_id = db.upsert_target(
        paths,
        name=args.name,
        url=args.url,
        kind=args.kind,
        high_stakes=not args.low_stakes,
        created_at=utc_now(),
    )
    print(f"Target {target_id} registered: {args.name}")
    return 0


def cmd_watch_run(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    db.init_db(paths)
    runs = run_all(paths, name=args.name)
    for run in runs:
        print(f"{run['run_id']} target={run['target_id']} alert={run['alert']['level']} status={run['status']['value']} reason={run['alert']['reason']}")
        print(f"  evidence={run['evidence']['path']}")
    return 0


def cmd_alerts(args: argparse.Namespace) -> int:
    print_json(db.list_alerts(paths_from_args(args), limit=args.limit))
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    print_json(db.list_runs(paths_from_args(args), limit=args.limit))
    return 0


def cmd_evidence(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    run = db.get_run(paths, args.run_id)
    if not run:
        print(f"No run found: {args.run_id}", file=sys.stderr)
        return 1
    evidence_path = Path(run["evidence"]["path"])
    if args.package:
        package_path = package_path_for(evidence_path)
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        write_evidence_package(package_path, evidence)
        print(str(package_path))
        return 0
    if args.report:
        report_path = Path(run["evidence"].get("report_path", ""))
        if not report_path.exists():
            print(f"No report found for run: {args.run_id}", file=sys.stderr)
            return 1
        print(str(report_path))
        return 0
    if args.redacted:
        redacted_path = Path(run["evidence"].get("redacted_path", ""))
        if redacted_path.exists():
            print(redacted_path.read_text(encoding="utf-8"))
        else:
            print_json(redact_data(json.loads(evidence_path.read_text(encoding="utf-8"))))
        return 0
    print(evidence_path.read_text(encoding="utf-8"))
    return 0


def cmd_chrome_launch(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    process = launch_chrome(paths, port=args.port, address=args.address)
    print(f"Chrome launched with PID {process.pid}")
    print(f"Profile: {paths.chrome_profile}")
    return 0


def cmd_plan_status(args: argparse.Namespace) -> int:
    summary = summarize_plan()
    if args.json:
        print_json(summary)
    else:
        print(format_plan_summary(summary))
    return 0


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
    state = db.get_connector_state(paths, connector="gmail_api", account_id=args.account)
    since = args.since if args.since is not None else str((state or {}).get("cursor") or "")
    config = GoogleOAuthConfig(
        credentials_json=env_secret(args.credentials_env),
        token_json=env_secret(args.token_env),
        scopes=(GMAIL_READONLY_SCOPE,),
        account_id=args.account,
    )
    client = GoogleWorkspaceFactory(config).gmail_client()
    setattr(client, "account_id", args.account)
    setattr(client, "scopes", config.scopes)
    summary = sync_connector(
        paths,
        GmailApiEmailConnector(client),
        EmailSyncRequest(query=args.query or "", since=since, limit=args.limit),
        account_id=args.account,
    )
    print_json({"oauth": config.safe_summary(), "sync": summary})
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
        query = args.query or "deadline OR due OR payment OR notice OR required OR action"
        config = GoogleOAuthConfig(
            credentials_json=env_secret(args.credentials_env),
            token_json=env_secret(args.token_env),
            scopes=(GMAIL_READONLY_SCOPE,),
            account_id=args.account,
        )
        client = GoogleWorkspaceFactory(config).gmail_client()
        setattr(client, "account_id", args.account)
        setattr(client, "scopes", config.scopes)
        summary = sync_connector(
            paths,
            GmailApiEmailConnector(client),
            EmailSyncRequest(query=query, since=since, limit=args.limit),
            account_id=args.account,
        )
        sync_summary = {
            "mode": "gmail_readonly",
            "external_network": True,
            "query": query,
            "oauth": _redacted_daily_oauth_summary(config.safe_summary()),
            **summary,
        }
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
    print_json(
        build_daily_landing_summary(
            paths,
            sync_summary=sync_summary,
            task_limit=args.task_limit,
            calendar_limit=args.calendar_limit,
            actor=args.actor,
        )
    )
    return 0


def _redacted_daily_oauth_summary(summary: dict[str, object]) -> dict[str, object]:
    safe = dict(summary)
    if safe.get("account_id"):
        safe["account_id"] = "[REDACTED_CONNECTOR_METADATA]"
    return safe


def cmd_audit_list(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    db.init_db(paths)
    print_json(db.list_audit_events(paths, limit=args.limit))
    return 0


def cmd_approvals_list(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    db.init_db(paths)
    print_json(db.list_approval_records(paths, limit=args.limit))
    return 0


def cmd_retention_purge(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    db.init_db(paths)
    sources = tuple(args.source) or ("email", "calendar", "tasks", "audit", "approvals")
    result = purge(paths, before=args.before, sources=sources, confirmed=True) if args.confirm else plan_purge(paths, before=args.before, sources=sources)
    print_json(result_to_dict(result))
    return 0


def cmd_privacy_audit(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    root = Path(args.path) if args.path else paths.artifacts
    result = audit_redacted_artifacts(root)
    print_json(result)
    return 1 if args.require_clean and result["status"] != "clean" else 0


def cmd_privacy_release_audit(args: argparse.Namespace) -> int:
    root = Path(args.path) if args.path else Path.cwd()
    result = audit_project_tree(root)
    print_json(result)
    return 1 if args.require_clean and result["status"] != "clean" else 0


def cmd_privacy_release_package(args: argparse.Namespace) -> int:
    source = Path(args.source) if args.source else Path.cwd()
    result = write_release_package(source, Path(args.output))
    print_json(result)
    return 0 if result["status"] == "written" else 1


def parse_metadata_pairs(pairs: list[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"metadata must be key=value: {pair}")
        key, value = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"metadata key cannot be empty: {pair}")
        metadata[key] = value.strip()
    return metadata


def cmd_rag_index(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    indexed = index_file(
        paths,
        args.file,
        source_id=args.source_id,
        source_type=args.source_type,
        trust_label=args.trust_label,
        title=args.title,
        metadata=parse_metadata_pairs(args.metadata or []),
    )
    print_json(indexed.__dict__)
    return 0


def cmd_rag_search(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    db.init_db(paths)
    results = search_index(paths, args.query, limit=args.limit)
    print_json([result.__dict__ for result in results])
    return 0


def cmd_rag_docs(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    db.init_db(paths)
    print_json(db.list_rag_documents(paths, limit=args.limit))
    return 0


def cmd_model_calls(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    db.init_db(paths)
    print_json(
        {
            "summary": db.model_calls_summary(paths),
            "calls": db.list_model_calls(paths, limit=args.limit),
        }
    )
    return 0


def cmd_model_status(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    provider = load_model_provider(paths)
    print_json({**provider.__dict__, "adapter": adapter_status_dict(provider)})
    return 0


def cmd_eval_email_extract(args: argparse.Namespace) -> int:
    report = evaluate_golden_path(args.golden)
    if args.report_md:
        output = Path(args.report_md)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_markdown_report(report), encoding="utf-8")
    if args.json:
        print_json(report.to_dict())
    else:
        print(render_text_summary(report))
        if args.report_md:
            print(f"report: {args.report_md}")
    return 0


def cmd_connectors_state(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    db.init_db(paths)
    print_json(db.list_connector_states(paths, limit=args.limit))
    return 0


def cmd_tasks_list(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    print_json(list_tasks(paths, status=args.status, kind=args.kind, limit=args.limit))
    return 0


def cmd_tasks_review(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    try:
        result = review_task(
            paths,
            task_id=args.task_id,
            status=args.status,
            note=args.note or "",
            actor=args.actor,
        )
    except ValueError as error:
        print_json({"error": str(error)})
        return 1
    print_json(
        {
            "task_id": result.task_id,
            "status": result.status,
            "note": result.note,
            "actor": result.actor,
            "updated_at": result.updated_at,
            "task": result.task,
        }
    )
    return 0


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


def cmd_serve(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    db.init_db(paths)
    serve(paths, host=args.host, port=args.port)
    return 0


def load_email_messages(path: str) -> list[EmailMessage]:
    return load_email_json(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentineldesk", description="Fail-loud local portal sentinel.")
    parser.add_argument("--home", help="Override SentinelDesk home directory")
    parser.add_argument("--version", action="version", version=f"SentinelDesk {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser("init", help="Initialize local config, database, and demo fixtures")
    init_parser.set_defaults(func=cmd_init)

    doctor_parser = sub.add_parser("doctor", help="Check local readiness")
    doctor_parser.set_defaults(func=cmd_doctor)

    demo = sub.add_parser("demo", help="Demo fixture helpers")
    demo_sub = demo.add_subparsers(dest="demo_command", required=True)
    demo_seed = demo_sub.add_parser("seed", help="Seed synthetic high-stakes portal targets")
    demo_seed.set_defaults(func=cmd_demo_seed)
    demo_scenarios = demo_sub.add_parser("scenarios", help="List synthetic portal scenarios")
    demo_scenarios.add_argument("--kind", choices=["generic", "opt", "appointment", "lease"])
    demo_scenarios.set_defaults(func=cmd_demo_scenarios)
    demo_apply = demo_sub.add_parser("apply", help="Apply a synthetic scenario to a demo target")
    demo_apply.add_argument("scenario")
    demo_apply.add_argument("--target-name", help="Override the scenario target name")
    demo_apply.add_argument("--run", action="store_true", help="Run the target after applying the scenario")
    demo_apply.set_defaults(func=cmd_demo_apply)
    demo_record = demo_sub.add_parser("record-prep", help="Prepare a complete local state for manual portfolio demo recording")
    demo_record.add_argument("--port", type=int, default=8787, help="Dashboard port to include in the printed serve command")
    demo_record.set_defaults(func=cmd_demo_record_prep)

    targets = sub.add_parser("targets", help="List watch targets")
    targets.set_defaults(func=cmd_targets)

    watch = sub.add_parser("watch", help="Manage and run watches")
    watch_sub = watch.add_subparsers(dest="watch_command", required=True)
    watch_add = watch_sub.add_parser("add", help="Add or update a watch target")
    watch_add.add_argument("--name", required=True)
    watch_add.add_argument("--url", required=True)
    watch_add.add_argument("--kind", default="generic", choices=["generic", "opt", "appointment", "job", "lease"])
    watch_add.add_argument("--low-stakes", action="store_true", help="Do not fail loud on unknown status")
    watch_add.set_defaults(func=cmd_watch_add)
    watch_run = watch_sub.add_parser("run", help="Run one or all watches")
    watch_run.add_argument("--name", help="Run only one target by name")
    watch_run.set_defaults(func=cmd_watch_run)

    alerts = sub.add_parser("alerts", help="List non-empty alerts")
    alerts.add_argument("--limit", type=int, default=50)
    alerts.set_defaults(func=cmd_alerts)

    runs = sub.add_parser("runs", help="List recent runs")
    runs.add_argument("--limit", type=int, default=50)
    runs.set_defaults(func=cmd_runs)

    evidence = sub.add_parser("evidence", help="Print an evidence bundle by run id")
    evidence.add_argument("run_id")
    evidence.add_argument("--redacted", action="store_true", help="Print the privacy-safe evidence bundle")
    evidence.add_argument("--report", action="store_true", help="Print the generated redacted HTML report path")
    evidence.add_argument("--package", action="store_true", help="Create a redacted shareable evidence ZIP package and print its path")
    evidence.set_defaults(func=cmd_evidence)

    plan = sub.add_parser("plan", help="Show plan-tracker status")
    plan_sub = plan.add_subparsers(dest="plan_command", required=True)
    plan_status = plan_sub.add_parser("status", help="Show completed plans and the next plan to complete")
    plan_status.add_argument("--json", action="store_true", help="Print machine-readable plan status")
    plan_status.set_defaults(func=cmd_plan_status)

    ask = sub.add_parser("ask", help="Ask the assistant layer with tool-first routing")
    ask.add_argument("question")
    ask.add_argument("--email-json", help="Local JSON file containing email messages for offline verification")
    ask.set_defaults(func=cmd_ask)

    daily = sub.add_parser("daily", help="Run the Gmail-first daily landing workflow")
    daily_sub = daily.add_subparsers(dest="daily_command", required=True)
    daily_run = daily_sub.add_parser("run", help="Refresh optional email evidence and summarize tasks/calendar drafts")
    daily_run.add_argument("--email-json", help="Optional local JSON email export to ingest before building the daily queue")
    daily_run.add_argument("--sync-gmail", action="store_true", help="Explicitly refresh Gmail through readonly OAuth before summarizing")
    daily_run.add_argument("--query", help="Optional email/Gmail search query for this refresh")
    daily_run.add_argument("--since", help="Override incremental Gmail cursor/date. Defaults to stored connector cursor.")
    daily_run.add_argument("--limit", type=int, default=50)
    daily_run.add_argument("--task-limit", type=int, default=12)
    daily_run.add_argument("--calendar-limit", type=int, default=20)
    daily_run.add_argument(
        "--reprocess-stored",
        action="store_true",
        help="Re-run current extractors over already stored local email before summarizing",
    )
    daily_run.add_argument("--reprocess-limit", type=int, default=500)
    daily_run.add_argument(
        "--no-calendar-drafts",
        action="store_true",
        help="When reprocessing, update email facts without upserting local calendar drafts",
    )
    daily_run.add_argument("--account", default="default")
    daily_run.add_argument("--actor", default="user")
    daily_run.add_argument("--credentials-env", default="SENTINEL_GOOGLE_CREDENTIALS_JSON")
    daily_run.add_argument("--token-env", default="SENTINEL_GOOGLE_TOKEN_JSON")
    daily_run.set_defaults(func=cmd_daily_run)

    rag = sub.add_parser("rag", help="Build and search the local RAG index")
    rag_sub = rag.add_subparsers(dest="rag_command", required=True)
    rag_index = rag_sub.add_parser("index", help="Index one local document into the persistent RAG store")
    rag_index.add_argument("file")
    rag_index.add_argument("--source-id")
    rag_index.add_argument("--source-type", default="local_doc")
    rag_index.add_argument("--trust-label", default="user_imported")
    rag_index.add_argument("--title", default="")
    rag_index.add_argument("--metadata", action="append", default=[], help="Attach document metadata as key=value; repeat for multiple values")
    rag_index.set_defaults(func=cmd_rag_index)
    rag_search = rag_sub.add_parser("search", help="Search the persistent RAG store")
    rag_search.add_argument("query")
    rag_search.add_argument("--limit", type=int, default=5)
    rag_search.set_defaults(func=cmd_rag_search)
    rag_docs = rag_sub.add_parser("docs", help="List indexed RAG documents")
    rag_docs.add_argument("--limit", type=int, default=50)
    rag_docs.set_defaults(func=cmd_rag_docs)

    model = sub.add_parser("model", help="Inspect configured model provider")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    model_status = model_sub.add_parser("status", help="Show active model provider and optional dependency availability")
    model_status.set_defaults(func=cmd_model_status)
    model_calls = model_sub.add_parser("calls", help="Show model call cost/latency attribution (tokens, duration, outcomes)")
    model_calls.add_argument("--limit", type=int, default=50)
    model_calls.set_defaults(func=cmd_model_calls)

    evals = sub.add_parser("eval", help="Run golden-set evals against extraction layers")
    evals_sub = evals.add_subparsers(dest="eval_command", required=True)
    eval_email = evals_sub.add_parser("email-extract", help="Score email fact extraction against the golden set")
    eval_email.add_argument("--golden", default="evals/golden", help="Golden JSONL file or directory")
    eval_email.add_argument("--report-md", help="Write a Markdown eval report to this path")
    eval_email.add_argument("--json", action="store_true", help="Print the full JSON report")
    eval_email.set_defaults(func=cmd_eval_email_extract)

    email = sub.add_parser("email", help="Ingest and inspect local email evidence")
    email_sub = email.add_subparsers(dest="email_command", required=True)
    email_scan = email_sub.add_parser("scan", help="Scan local JSON email export and draft calendar events")
    email_scan.add_argument("--json", required=True, help="Local JSON file containing email messages")
    email_scan.add_argument("--query", help="Optional query to filter messages before ingest")
    email_scan.add_argument("--limit", type=int, default=50)
    email_scan.set_defaults(func=cmd_email_scan)
    email_sync_gmail = email_sub.add_parser("sync-gmail", help="Sync Gmail through an authenticated Google client")
    email_sync_gmail.add_argument("--query", help="Optional Gmail search query")
    email_sync_gmail.add_argument("--since", help="Override incremental cursor/date. Defaults to stored connector cursor.")
    email_sync_gmail.add_argument("--limit", type=int, default=50)
    email_sync_gmail.add_argument("--account", default="default")
    email_sync_gmail.add_argument("--credentials-env", default="SENTINEL_GOOGLE_CREDENTIALS_JSON")
    email_sync_gmail.add_argument("--token-env", default="SENTINEL_GOOGLE_TOKEN_JSON")
    email_sync_gmail.set_defaults(func=cmd_email_sync_gmail)
    email_reprocess = email_sub.add_parser("reprocess", help="Re-run current extractors over stored local email evidence")
    email_reprocess.add_argument("--limit", type=int, default=500)
    email_reprocess.add_argument("--no-calendar-drafts", action="store_true", help="Update stored facts without upserting local calendar drafts")
    email_reprocess.set_defaults(func=cmd_email_reprocess)

    tasks = sub.add_parser("tasks", help="Review extracted LifeAgent tasks")
    tasks_sub = tasks.add_subparsers(dest="tasks_command", required=True)
    tasks_list = tasks_sub.add_parser("list", help="List task-review items derived from email facts and local drafts")
    tasks_list.add_argument("--status", choices=["new", "reviewed", "ignored", "needs_verification", "done"])
    tasks_list.add_argument("--kind", choices=["deadline", "amount", "action"])
    tasks_list.add_argument("--limit", type=int, default=100)
    tasks_list.set_defaults(func=cmd_tasks_list)
    tasks_review = tasks_sub.add_parser("review", help="Set review status for one task")
    tasks_review.add_argument("--task-id", required=True)
    tasks_review.add_argument("--status", required=True, choices=["new", "reviewed", "ignored", "needs_verification", "done"])
    tasks_review.add_argument("--note", default="")
    tasks_review.add_argument("--actor", default="user")
    tasks_review.set_defaults(func=cmd_tasks_review)

    calendar = sub.add_parser("calendar", help="Preview or sync drafted calendar deadline events")
    calendar_sub = calendar.add_subparsers(dest="calendar_command", required=True)
    calendar_sync = calendar_sub.add_parser("sync", help="Sync calendar drafts after explicit confirmation")
    calendar_sync.add_argument("--destination", choices=["ics", "google", "apple"], default="ics")
    calendar_sync.add_argument("--event-id", help="Sync only one local LifeAgent event id")
    calendar_sync.add_argument("--limit", type=int, default=200)
    calendar_sync.add_argument("--account", default="default")
    calendar_sync.add_argument("--calendar-id", default="", help="Google calendar id or Apple calendar URL/name; defaults to primary for Google and default for Apple")
    calendar_sync.add_argument("--actor", default="user")
    calendar_sync.add_argument("--confirm", action="store_true", help="Allow the calendar write")
    calendar_sync.add_argument("--confirmation-id", default="", help="Required stable confirmation id for external writes")
    calendar_sync.add_argument("--output", help="ICS output path when destination=ics")
    calendar_sync.add_argument("--google-credentials-env", default="SENTINEL_GOOGLE_CREDENTIALS_JSON")
    calendar_sync.add_argument("--google-token-env", default="SENTINEL_GOOGLE_TOKEN_JSON")
    calendar_sync.add_argument("--apple-user-env", default="SENTINEL_APPLE_ID")
    calendar_sync.add_argument("--apple-password-env", default="SENTINEL_APPLE_APP_PASSWORD")
    calendar_sync.set_defaults(func=cmd_calendar_sync)
    calendar_edit = calendar_sub.add_parser("edit", help="Edit a local calendar draft before external sync")
    calendar_edit.add_argument("--event-id", required=True)
    calendar_edit.add_argument("--title")
    calendar_edit.add_argument("--date", help="Replacement date text for the local deadline draft")
    calendar_edit.add_argument("--severity", choices=["low", "medium", "critical"])
    calendar_edit.add_argument("--actor", default="user")
    calendar_edit.set_defaults(func=cmd_calendar_edit)

    connectors = sub.add_parser("connectors", help="Inspect connector sync state")
    connectors_sub = connectors.add_subparsers(dest="connectors_command", required=True)
    connectors_state = connectors_sub.add_parser("state", help="List connector cursors and metadata")
    connectors_state.add_argument("--limit", type=int, default=50)
    connectors_state.set_defaults(func=cmd_connectors_state)

    integrations = sub.add_parser("integrations", help="Run live/sandbox integration readiness checks")
    integrations_sub = integrations.add_subparsers(dest="integrations_command", required=True)
    integrations_check = integrations_sub.add_parser("check", help="Check external integration readiness without exposing secrets")
    integrations_check.add_argument("--suite", choices=["all", "gmail", "calendar", "langgraph", "sandbox"], default="all")
    integrations_check.add_argument("--account", default="default")
    integrations_check.add_argument("--google-credentials-env", default="SENTINEL_GOOGLE_CREDENTIALS_JSON")
    integrations_check.add_argument("--google-token-env", default="SENTINEL_GOOGLE_TOKEN_JSON")
    integrations_check.add_argument("--apple-user-env", default="SENTINEL_APPLE_ID")
    integrations_check.add_argument("--apple-password-env", default="SENTINEL_APPLE_APP_PASSWORD")
    integrations_check.add_argument("--no-persist", action="store_true", help="Print the report without saving it")
    integrations_check.add_argument("--package", action="store_true", help="Also write a redacted ZIP package for this report")
    integrations_check.add_argument("--require-ready", action="store_true", help="Exit non-zero unless every check is ready")
    integrations_check.set_defaults(func=cmd_integrations_check)
    integrations_reports = integrations_sub.add_parser("reports", help="List stored integration verification reports")
    integrations_reports.add_argument("--limit", type=int, default=20)
    integrations_reports.set_defaults(func=cmd_integrations_reports)
    integrations_audit = integrations_sub.add_parser("completion-audit", help="Audit whether final live verification evidence is complete")
    integrations_audit.add_argument("--account", default="default")
    integrations_audit.add_argument("--google-credentials-env", default="SENTINEL_GOOGLE_CREDENTIALS_JSON")
    integrations_audit.add_argument("--google-token-env", default="SENTINEL_GOOGLE_TOKEN_JSON")
    integrations_audit.add_argument("--apple-user-env", default="SENTINEL_APPLE_ID")
    integrations_audit.add_argument("--apple-password-env", default="SENTINEL_APPLE_APP_PASSWORD")
    integrations_audit.add_argument("--source-release-path", default="/tmp/extracted-sentineldesk")
    integrations_audit.add_argument("--require-ready", action="store_true", help="Exit non-zero unless final live verification evidence is complete")
    integrations_audit.set_defaults(func=cmd_integrations_completion_audit)
    integrations_handoff = integrations_sub.add_parser("handoff", help="Render a human-readable live verification handoff checklist")
    integrations_handoff.add_argument("--account", default="default")
    integrations_handoff.add_argument("--google-credentials-env", default="SENTINEL_GOOGLE_CREDENTIALS_JSON")
    integrations_handoff.add_argument("--google-token-env", default="SENTINEL_GOOGLE_TOKEN_JSON")
    integrations_handoff.add_argument("--apple-user-env", default="SENTINEL_APPLE_ID")
    integrations_handoff.add_argument("--apple-password-env", default="SENTINEL_APPLE_APP_PASSWORD")
    integrations_handoff.add_argument("--source-release-path", default="/tmp/extracted-sentineldesk")
    integrations_handoff.add_argument("--output", help="Write the Markdown checklist to this path instead of stdout")
    integrations_handoff.add_argument("--require-ready", action="store_true", help="Exit non-zero unless final live verification evidence is complete")
    integrations_handoff.set_defaults(func=cmd_integrations_handoff)
    integrations_package = integrations_sub.add_parser("package", help="Create a redacted ZIP package for an integration verification report")
    integrations_package.add_argument("verification_id", help="Verification id to package, or 'latest'")
    integrations_package.add_argument("--output", help="Output ZIP path")
    integrations_package.set_defaults(func=cmd_integrations_package)
    integrations_seed_calendar = integrations_sub.add_parser(
        "seed-calendar-draft",
        help="Create a local verification calendar draft for live calendar sync tests",
    )
    integrations_seed_calendar.add_argument("--title", default="Deadline: LifeAgent live calendar verification")
    integrations_seed_calendar.add_argument("--date", default="2026-07-15")
    integrations_seed_calendar.add_argument("--source-id", default="live-verification:manual-calendar-draft")
    integrations_seed_calendar.add_argument("--evidence-uri", default="live-verification://manual-calendar-draft")
    integrations_seed_calendar.add_argument("--severity", choices=["low", "medium", "critical"], default="medium")
    integrations_seed_calendar.add_argument("--confidence", type=float, default=1.0)
    integrations_seed_calendar.add_argument("--actor", default="user")
    integrations_seed_calendar.set_defaults(func=cmd_integrations_seed_calendar_draft)
    integrations_env = integrations_sub.add_parser("env-template", help="Print redacted live-integration env setup commands")
    integrations_env.add_argument("--account", default="user@example.com")
    integrations_env.add_argument("--google-credentials-env", default="SENTINEL_GOOGLE_CREDENTIALS_JSON")
    integrations_env.add_argument("--google-token-env", default="SENTINEL_GOOGLE_TOKEN_JSON")
    integrations_env.add_argument("--apple-user-env", default="SENTINEL_APPLE_ID")
    integrations_env.add_argument("--apple-password-env", default="SENTINEL_APPLE_APP_PASSWORD")
    integrations_env.set_defaults(func=cmd_integrations_env_template)
    integrations_token = integrations_sub.add_parser("google-token", help="Run local Google OAuth and write token JSON without printing it")
    integrations_token.add_argument("--credentials-env", default="SENTINEL_GOOGLE_CREDENTIALS_JSON")
    integrations_token.add_argument("--token-env", default="SENTINEL_GOOGLE_TOKEN_JSON")
    integrations_token.add_argument("--token-output", help="Local token JSON output path. Defaults to <home>/secrets/google-token.json")
    integrations_token.add_argument("--scope", action="append", choices=["gmail.readonly", "calendar.events"], help="Google OAuth scope alias; repeat to limit scopes")
    integrations_token.add_argument("--port", type=int, default=0, help="Local OAuth callback port; 0 lets the OS choose")
    integrations_token.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically")
    integrations_token.set_defaults(func=cmd_integrations_google_token)

    audit = sub.add_parser("audit", help="Inspect local audit trail")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)
    audit_list = audit_sub.add_parser("list", help="List recent audit events")
    audit_list.add_argument("--limit", type=int, default=50)
    audit_list.set_defaults(func=cmd_audit_list)

    approvals = sub.add_parser("approvals", help="Inspect durable user approval records")
    approvals_sub = approvals.add_subparsers(dest="approvals_command", required=True)
    approvals_list = approvals_sub.add_parser("list", help="List recent approval records")
    approvals_list.add_argument("--limit", type=int, default=50)
    approvals_list.set_defaults(func=cmd_approvals_list)

    retention = sub.add_parser("retention", help="Preview or execute local retention purges")
    retention_sub = retention.add_subparsers(dest="retention_command", required=True)
    retention_purge = retention_sub.add_parser("purge", help="Purge local records older than --before")
    retention_purge.add_argument("--before", required=True, help="Delete records with timestamps before this ISO-like value")
    retention_purge.add_argument(
        "--source",
        action="append",
        choices=["email", "calendar", "tasks", "audit", "approvals"],
        default=[],
        help="Source to purge; repeat for multiple. Defaults to all sources.",
    )
    retention_purge.add_argument("--confirm", action="store_true", help="Actually delete matching local records")
    retention_purge.set_defaults(func=cmd_retention_purge)

    privacy = sub.add_parser("privacy", help="Audit redacted share outputs for private data leaks")
    privacy_sub = privacy.add_subparsers(dest="privacy_command", required=True)
    privacy_audit = privacy_sub.add_parser("audit", help="Scan redacted reports and share packages for unredacted private data")
    privacy_audit.add_argument("--path", help="Directory to scan. Defaults to <home>/artifacts")
    privacy_audit.add_argument("--require-clean", action="store_true", help="Exit non-zero when leaks are found")
    privacy_audit.set_defaults(func=cmd_privacy_audit)
    privacy_release = privacy_sub.add_parser("release-audit", help="Scan the project tree for local runtime artifacts before public release")
    privacy_release.add_argument("--path", help="Project directory to scan. Defaults to the current working directory")
    privacy_release.add_argument("--require-clean", action="store_true", help="Exit non-zero when release artifacts are found")
    privacy_release.set_defaults(func=cmd_privacy_release_audit)
    privacy_package = privacy_sub.add_parser("release-package", help="Write a public source ZIP excluding local runtime artifacts")
    privacy_package.add_argument("--source", help="Project directory to package. Defaults to the current working directory")
    privacy_package.add_argument("--output", required=True, help="Output ZIP path")
    privacy_package.set_defaults(func=cmd_privacy_release_package)

    chrome = sub.add_parser("chrome", help="Chrome automation profile")
    chrome_sub = chrome.add_subparsers(dest="chrome_command", required=True)
    chrome_launch = chrome_sub.add_parser("launch", help="Launch dedicated Chrome debugging profile")
    chrome_launch.add_argument("--port", type=int, default=9222)
    chrome_launch.add_argument("--address", default="127.0.0.1")
    chrome_launch.set_defaults(func=cmd_chrome_launch)

    server = sub.add_parser("serve", help="Serve local dashboard")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8787)
    server.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
