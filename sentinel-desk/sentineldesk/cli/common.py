"""Shared CLI helpers used across the command modules."""

from __future__ import annotations

import argparse
import json

from ..config import get_paths


def print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def paths_from_args(args: argparse.Namespace):
    return get_paths(getattr(args, "home", None))
