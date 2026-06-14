"""Core setup/ops commands: init, doctor, acceptance, plan, chrome, serve."""

from __future__ import annotations

import argparse

from .. import db
from ..acceptance import run_first_run_acceptance
from ..chrome import launch as launch_chrome
from ..config import ensure_config, ensure_dirs, seed_demo_fixtures
from ..plantracker import format_plan_summary, summarize_plan
from ..server import serve
from .common import paths_from_args, print_json


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


def cmd_acceptance_first_run(args: argparse.Namespace) -> int:
    result = run_first_run_acceptance(
        paths_from_args(args),
        sample_email_json=args.email_json,
        port=args.port,
    )
    print_json(result)
    return 0 if result["status"] == "passed" else 1


def cmd_plan_status(args: argparse.Namespace) -> int:
    summary = summarize_plan()
    if args.json:
        print_json(summary)
    else:
        print(format_plan_summary(summary))
    return 0


def cmd_chrome_launch(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    process = launch_chrome(paths, port=args.port, address=args.address)
    print(f"Chrome launched with PID {process.pid}")
    print(f"Profile: {paths.chrome_profile}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    db.init_db(paths)
    serve(paths, host=args.host, port=args.port)
    return 0
