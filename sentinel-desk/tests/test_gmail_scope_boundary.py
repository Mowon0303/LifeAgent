"""The Gmail-first rollout is readonly, and that has to be enforced, not intended.

Checking only that `gmail.readonly` is present leaves the dangerous half unchecked:
a token that *also* carries `calendar.events` can write to the user's real
calendar. Requesting readonly is now the default, but the token is what actually
grants access, so the boundary is asserted against the token.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from sentineldesk.config import get_paths
from sentineldesk.gmail_readiness import FORBIDDEN_GMAIL_FIRST_SCOPES, build_gmail_readiness
from sentineldesk.integrations.google_oauth import (
    CALENDAR_WRITE_SCOPES,
    DEFAULT_GOOGLE_SCOPES,
    normalize_google_scopes,
)
from sentineldesk.integrations.google_workspace import CALENDAR_EVENTS_SCOPE, GMAIL_READONLY_SCOPE

TOKEN_ENV = "SENTINEL_TEST_SCOPE_BOUNDARY_TOKEN"


def _readiness_with_token(scopes: list[str]) -> dict:
    old = os.environ.get(TOKEN_ENV)
    os.environ[TOKEN_ENV] = json.dumps({"token": "x", "scopes": scopes})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            return build_gmail_readiness(get_paths(Path(tmp)), token_env=TOKEN_ENV)
    finally:
        if old is None:
            os.environ.pop(TOKEN_ENV, None)
        else:
            os.environ[TOKEN_ENV] = old


def _check(readiness: dict, name: str) -> dict:
    return next(item for item in readiness["checks"] if item["name"] == name)


class ScopeDefaultTests(unittest.TestCase):
    def test_default_scopes_are_readonly_only(self) -> None:
        self.assertEqual(DEFAULT_GOOGLE_SCOPES, (GMAIL_READONLY_SCOPE,))
        self.assertNotIn(CALENDAR_EVENTS_SCOPE, DEFAULT_GOOGLE_SCOPES)

    def test_omitting_scopes_never_requests_calendar_write(self) -> None:
        """A write scope must require asking for it, never come from omission."""
        self.assertEqual(normalize_google_scopes(None), (GMAIL_READONLY_SCOPE,))
        self.assertEqual(normalize_google_scopes([]), (GMAIL_READONLY_SCOPE,))

    def test_calendar_write_is_still_reachable_when_asked_for(self) -> None:
        self.assertEqual(normalize_google_scopes(["calendar.events"]), CALENDAR_WRITE_SCOPES)


class ScopeBoundaryCheckTests(unittest.TestCase):
    def test_readonly_token_passes_the_boundary(self) -> None:
        readiness = _readiness_with_token([GMAIL_READONLY_SCOPE])
        boundary = _check(readiness, "gmail.scope_boundary")
        self.assertEqual(boundary["status"], "ready", boundary["detail"])
        self.assertEqual(boundary["metadata"]["granted_write_scopes"], [])

    def test_calendar_write_token_fails_the_boundary(self) -> None:
        readiness = _readiness_with_token([GMAIL_READONLY_SCOPE, CALENDAR_EVENTS_SCOPE])
        boundary = _check(readiness, "gmail.scope_boundary")
        self.assertEqual(boundary["status"], "invalid", boundary["detail"])
        self.assertIn(CALENDAR_EVENTS_SCOPE, boundary["metadata"]["granted_write_scopes"])
        # The read-scope check alone would have called this fine — that is the gap.
        self.assertEqual(_check(readiness, "gmail.token_scope")["status"], "ready")
        self.assertNotEqual(readiness["status"], "ready")

    def test_every_forbidden_scope_is_rejected(self) -> None:
        for scope in FORBIDDEN_GMAIL_FIRST_SCOPES:
            with self.subTest(scope=scope):
                readiness = _readiness_with_token([GMAIL_READONLY_SCOPE, scope])
                self.assertEqual(_check(readiness, "gmail.scope_boundary")["status"], "invalid")

    def test_boundary_result_never_echoes_the_token(self) -> None:
        readiness = _readiness_with_token([GMAIL_READONLY_SCOPE])
        self.assertNotIn("\"token\": \"x\"", json.dumps(readiness))
        self.assertIn(f"env:{TOKEN_ENV}:***", json.dumps(readiness))


if __name__ == "__main__":
    unittest.main()
