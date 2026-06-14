"""Data-lifecycle commands: retention purge and release/privacy audits."""

from __future__ import annotations

import argparse
from pathlib import Path

from .. import db
from ..privacy import audit_project_tree, audit_redacted_artifacts, write_release_package
from ..retention import plan_purge, purge, result_to_dict
from .common import paths_from_args, print_json


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
