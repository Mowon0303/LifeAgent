"""Copy-pasteable env-var lines for the shell the user is actually in.

A "next step" the user cannot paste is not a next step. These hints are printed
by readiness and OAuth flows, and on Windows the POSIX forms are not merely
ugly -- ``export`` is not a command, ``$(cat file)`` is not substitution, and
the line fails with no indication that a shell mismatch is the reason.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path


def is_powershell() -> bool:
    """True when the hint should be written for PowerShell rather than sh."""
    return sys.platform.startswith("win")


def env_literal_hint(name: str, value: str) -> str:
    """A line that sets ``name`` to a literal ``value``."""
    if is_powershell():
        return f"$env:{name} = '{value.replace(chr(39), chr(39) * 2)}'"
    return f"export {name}={shlex.quote(value)}"


def env_from_file_hint(name: str, path: str | Path) -> str:
    """A line that sets ``name`` to the entire contents of ``path``.

    ``-Raw`` matters: without it PowerShell hands back an array of lines and the
    variable ends up holding a mangled token rather than the JSON.
    """
    text = str(path)
    if is_powershell():
        return f'$env:{name} = Get-Content -Raw "{text}"'
    return f'export {name}="$(cat {shlex.quote(text)})"'
