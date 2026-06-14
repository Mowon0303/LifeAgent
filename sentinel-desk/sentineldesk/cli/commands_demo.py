"""Demo fixture and scenario commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .. import db
from ..config import ensure_config, ensure_dirs, project_root, seed_demo_fixtures
from ..email.ingest import ingest_messages, load_email_json
from ..monitor import run_all
from ..reports import package_path_for, write_evidence_package
from ..scenarios import apply_scenario, list_scenarios
from ..tasks import list_tasks
from .common import paths_from_args, print_json


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
