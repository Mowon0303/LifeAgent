"""Local-ledger inspection commands: audit, approvals, connectors, model, eval."""

from __future__ import annotations

import argparse
from pathlib import Path

from .. import db
from ..agent.model import load_model_provider
from ..agent.providers import adapter_status_dict
from ..evals.email_extract import evaluate_golden_path, render_markdown_report, render_text_summary
from .common import paths_from_args, print_json


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


def cmd_connectors_state(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    db.init_db(paths)
    print_json(db.list_connector_states(paths, limit=args.limit))
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
