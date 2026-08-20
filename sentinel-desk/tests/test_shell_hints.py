"""A "next step" the user cannot paste is not a next step.

Readiness output and the OAuth flow both print env-var lines. On Windows the
POSIX forms do not merely look wrong -- ``export`` is not a command and
``$(cat ...)`` is not substitution, so the line fails with nothing to suggest
that a shell mismatch is the reason. These tests pin both shells regardless of
the host running them.
"""

from __future__ import annotations

import unittest
from unittest import mock

from sentineldesk import shell_hints
from sentineldesk.gmail_readiness import build_gmail_readiness


class HintShapeTests(unittest.TestCase):
    def test_powershell_reads_the_file_with_raw(self) -> None:
        with mock.patch.object(shell_hints, "is_powershell", return_value=True):
            line = shell_hints.env_from_file_hint("SENTINEL_TOKEN", r"C:\secrets\token.json")
        # Without -Raw, PowerShell yields an array of lines and the variable
        # ends up holding a mangled token instead of the JSON.
        self.assertEqual(line, r'$env:SENTINEL_TOKEN = Get-Content -Raw "C:\secrets\token.json"')

    def test_posix_reads_the_file_with_cat(self) -> None:
        with mock.patch.object(shell_hints, "is_powershell", return_value=False):
            line = shell_hints.env_from_file_hint("SENTINEL_TOKEN", "/home/u/token.json")
        self.assertEqual(line, 'export SENTINEL_TOKEN="$(cat /home/u/token.json)"')

    def test_posix_quotes_a_path_with_spaces(self) -> None:
        with mock.patch.object(shell_hints, "is_powershell", return_value=False):
            line = shell_hints.env_from_file_hint("T", "/home/my user/token.json")
        self.assertIn("'/home/my user/token.json'", line)

    def test_a_literal_value_is_quoted_for_each_shell(self) -> None:
        with mock.patch.object(shell_hints, "is_powershell", return_value=True):
            self.assertEqual(shell_hints.env_literal_hint("T", "it's"), "$env:T = 'it''s'")
        with mock.patch.object(shell_hints, "is_powershell", return_value=False):
            self.assertEqual(shell_hints.env_literal_hint("T", "it's"), "export T='it'\"'\"'s'")


class ReadinessNextActionTests(unittest.TestCase):
    """The hint the user actually meets in the Gmail landing flow."""

    def test_the_credentials_next_action_matches_the_host_shell(self) -> None:
        import tempfile
        from pathlib import Path

        from sentineldesk import db
        from sentineldesk.config import get_paths

        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(Path(tmp))
            db.init_db(paths)
            with mock.patch.dict("os.environ", {}, clear=False):
                readiness = build_gmail_readiness(paths, account_id="default")
        command = str((readiness.get("next_action") or {}).get("command") or "")
        if not command.startswith("$env:") and not command.startswith("export "):
            return  # a different next step (install deps, run sync) is fine here
        if shell_hints.is_powershell():
            self.assertTrue(command.startswith("$env:"), command)
            self.assertNotIn("$(cat", command)
        else:
            self.assertTrue(command.startswith("export "), command)


if __name__ == "__main__":
    unittest.main()
