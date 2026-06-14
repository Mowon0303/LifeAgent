"""Portal monitor commands: targets, watch, alerts, runs, evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import db
from ..config import ensure_dirs
from ..extract import utc_now
from ..monitor import run_all
from ..reports import package_path_for, redact_data, write_evidence_package
from .common import paths_from_args, print_json


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
