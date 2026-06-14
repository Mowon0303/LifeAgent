"""Command-line interface.

Historically a single ``cli.py`` with ~50 ``cmd_*`` functions and one large
``build_parser``. Now a package: ``common`` holds shared helpers, the
``commands_*`` modules hold the command logic grouped by domain, and ``parser``
wires the argparse tree + ``main``. The public surface (``main``) is unchanged,
so ``from sentineldesk.cli import main`` keeps working.
"""

from __future__ import annotations

from .common import paths_from_args, print_json
from .parser import build_parser, main

__all__ = ["main", "build_parser", "print_json", "paths_from_args"]
