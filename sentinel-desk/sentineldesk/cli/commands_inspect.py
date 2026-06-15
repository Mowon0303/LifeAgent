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


def _eval_chat_client(args: argparse.Namespace):
    """Build a chat client for the LLM-in-the-loop evals, or None (keyword-only)."""
    if getattr(args, "provider", "local") == "local":
        return None
    from ..agent.llm import chat_client_for
    from ..agent.model import ModelProvider

    return chat_client_for(ModelProvider(provider=args.provider, model=args.model, base_url=args.base_url))


def cmd_eval_agent_routing(args: argparse.Namespace) -> int:
    from ..evals.agent_eval import evaluate_routing, render_routing_summary

    report = evaluate_routing(args.golden, client=_eval_chat_client(args))
    if args.json:
        print_json(report.to_dict())
    else:
        print(render_routing_summary(report))
    return 0


def cmd_eval_calendar_slots(args: argparse.Namespace) -> int:
    from ..evals.agent_eval import evaluate_slots, render_slots_summary

    client = _eval_chat_client(args)
    if client is None:
        print("calendar-slots eval needs a model — pass --provider ollama")
        return 2
    report = evaluate_slots(args.golden, client=client)
    if args.json:
        print_json(report.to_dict())
    else:
        print(render_slots_summary(report))
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
