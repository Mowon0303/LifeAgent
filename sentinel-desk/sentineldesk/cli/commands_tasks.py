"""Task review commands: list, review, history, receipt, bulk-review, undo."""

from __future__ import annotations

import argparse

from ..tasks import (
    build_review_receipt_summary,
    bulk_review_tasks,
    list_review_history,
    list_tasks,
    review_task,
    undo_task_review,
)
from .common import paths_from_args, print_json


def cmd_tasks_list(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    print_json(list_tasks(paths, status=args.status, kind=args.kind, sort=args.sort, view=args.view, limit=args.limit))
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


def cmd_tasks_history(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    print_json(list_review_history(paths, limit=args.limit))
    return 0


def cmd_tasks_receipt(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    print_json(build_review_receipt_summary(paths, limit=args.limit, recent_limit=args.recent_limit))
    return 0


def cmd_tasks_bulk_review(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    try:
        result = bulk_review_tasks(
            paths,
            status=args.status,
            kind=args.kind,
            status_filter=args.filter_status,
            limit=args.limit,
            note=args.note or "",
            actor=args.actor,
            confirmed=args.confirm,
            confirmation_id=args.confirmation_id,
        )
    except ValueError as error:
        print_json({"error": str(error)})
        return 1
    print_json(result.__dict__)
    return 0 if result.allowed or not args.confirm else 1


def cmd_tasks_undo(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    try:
        result = undo_task_review(
            paths,
            audit_id=args.audit_id,
            actor=args.actor,
            confirmed=args.confirm,
            confirmation_id=args.confirmation_id,
        )
    except ValueError as error:
        print_json({"error": str(error)})
        return 1
    print_json(result.__dict__)
    return 0 if result.allowed or not args.confirm else 1
