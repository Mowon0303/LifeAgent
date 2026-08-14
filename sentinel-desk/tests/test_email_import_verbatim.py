"""An imported mailbox is evidence, so the importer must not rewrite it.

`{{today+N}}` tokens exist so the *synthetic* demo inbox stays actionable instead
of rotting into expired deadlines. That substitution must never reach real mail:
a message whose body literally says `{{today+8}}` has to still say it after
loading, or the local evidence no longer matches what the sender actually wrote.

The enabling boundary is the caller's explicit choice — never the file's name,
directory, or contents.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from sentineldesk import db
from sentineldesk.cli import main
from sentineldesk.config import get_paths, project_root
from sentineldesk.email.connectors import EmailSyncRequest, LocalJsonEmailConnector
from sentineldesk.email.ingest import load_email_json, load_fixture_email_json

from tests.dates import each_baseline, pinned

SAMPLE_EMAILS = project_root() / "fixtures" / "ui" / "sample_emails.json"

LITERAL_BODY = "Keep literal {{today+8}} exactly as written."
LITERAL_SUBJECT = "Template docs {{today+3}}"
LITERAL_ATTACHMENT = "attachment says {{today-1}}"
LITERAL_RECEIVED = "2026-01-02T00:00:00+00:00"


def _write_user_export(directory: Path, name: str = "user_export.json") -> Path:
    path = directory / name
    path.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "message_id": "real-1",
                        "thread_id": "real-thread",
                        "sender": "ops@example.com",
                        "subject": LITERAL_SUBJECT,
                        "received_at": LITERAL_RECEIVED,
                        "body_text": LITERAL_BODY,
                        "attachment_texts": [LITERAL_ATTACHMENT],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


class VerbatimImportTests(unittest.TestCase):
    def _assert_verbatim(self, message) -> None:
        self.assertEqual(message.subject, LITERAL_SUBJECT)
        self.assertEqual(message.body_text, LITERAL_BODY)
        self.assertEqual(message.attachment_texts, (LITERAL_ATTACHMENT,))
        self.assertEqual(message.received_at, LITERAL_RECEIVED)

    def test_load_email_json_is_verbatim_by_default(self) -> None:
        for label, day in each_baseline():
            with self.subTest(baseline=label), pinned(day), tempfile.TemporaryDirectory() as tmp:
                path = _write_user_export(Path(tmp))
                self._assert_verbatim(load_email_json(path)[0])

    def test_connector_is_verbatim_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_user_export(Path(tmp))
            result = LocalJsonEmailConnector(path).search(EmailSyncRequest(limit=10))
            self._assert_verbatim(result.messages[0])

    def test_file_name_and_location_do_not_enable_substitution(self) -> None:
        """Naming a real export like the fixture must not change how it loads."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture_dir = Path(tmp) / "fixtures" / "ui"
            fixture_dir.mkdir(parents=True)
            path = _write_user_export(fixture_dir, name="sample_emails.json")
            self._assert_verbatim(load_email_json(path)[0])
            self._assert_verbatim(LocalJsonEmailConnector(path).search(EmailSyncRequest()).messages[0])

    def test_cli_email_scan_stores_the_literal_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            path = _write_user_export(Path(tmp))
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["--home", str(home), "email", "scan", "--json", str(path)])
            self.assertEqual(code, 0)
            stored = db.list_email_messages(get_paths(str(home)), limit=10)[0]

        self.assertEqual(stored["subject"], LITERAL_SUBJECT)
        self.assertEqual(stored["body_text"], LITERAL_BODY)
        self.assertEqual(list(stored["attachment_texts"]), [LITERAL_ATTACHMENT])

    def test_cli_daily_run_stores_the_literal_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            path = _write_user_export(Path(tmp))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--home", str(home), "daily", "run", "--email-json", str(path)])
            self.assertEqual(code, 0)
            summary = json.loads(output.getvalue())
            stored = db.list_email_messages(get_paths(str(home)), limit=10)[0]

        self.assertFalse(summary["sync"]["fixture_dates_materialized"])
        self.assertEqual(stored["body_text"], LITERAL_BODY)

    def test_acceptance_with_a_user_supplied_file_is_verbatim(self) -> None:
        """`--email-json <my file>` is an import, not a fixture."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            path = _write_user_export(Path(tmp))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main(["--home", str(home), "acceptance", "first-run", "--email-json", str(path)])
            payload = json.loads(output.getvalue())
            stored = db.list_email_messages(get_paths(str(home)), limit=10)[0]

        self.assertFalse(payload["fixture_dates_materialized"])
        self.assertEqual(stored["body_text"], LITERAL_BODY)


class FixtureOptInTests(unittest.TestCase):
    """The synthetic fixture path still works — but only when asked for."""

    def test_fixture_loader_materializes_the_sample_inbox(self) -> None:
        for label, day in each_baseline():
            with self.subTest(baseline=label), pinned(day):
                messages = load_fixture_email_json(SAMPLE_EMAILS)
                joined = " ".join(m.body_text + m.subject + m.received_at for m in messages)
                self.assertNotIn("{{today", joined)

    def test_same_fixture_read_verbatim_keeps_its_tokens(self) -> None:
        messages = load_email_json(SAMPLE_EMAILS)
        joined = " ".join(m.body_text for m in messages)
        self.assertIn("{{today", joined, "default load must not substitute anything")

    def test_explicit_opt_in_materializes_a_user_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_user_export(Path(tmp))
            message = load_email_json(path, materialize_date_tokens=True)[0]
            self.assertNotIn("{{today", message.body_text)

    def test_cli_fixture_dates_flag_opts_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(
                    ["--home", str(home), "daily", "run", "--email-json", str(SAMPLE_EMAILS), "--fixture-dates"]
                )
            self.assertEqual(code, 0)
            summary = json.loads(output.getvalue())
            stored = db.list_email_messages(get_paths(str(home)), limit=10)

        self.assertTrue(summary["sync"]["fixture_dates_materialized"])
        self.assertNotIn("{{today", " ".join(row["body_text"] for row in stored))

    def test_substitution_only_touches_message_date_fields(self) -> None:
        """Ids, senders and thread keys are carried through untouched."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.json"
            path.write_text(
                json.dumps(
                    {
                        "messages": [
                            {
                                "message_id": "id-{{today+1}}",
                                "thread_id": "thread-{{today+1}}",
                                "sender": "{{today+1}}@example.com",
                                "subject": "due {{today+1}}",
                                "received_at": "{{today-1}}T09:00:00+00:00",
                                "body_text": "pay by {{today+1}}",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            message = load_email_json(path, materialize_date_tokens=True)[0]

        self.assertEqual(message.message_id, "id-{{today+1}}")
        self.assertEqual(message.thread_id, "thread-{{today+1}}")
        self.assertEqual(message.sender, "{{today+1}}@example.com")
        self.assertNotIn("{{today", message.subject)
        self.assertNotIn("{{today", message.body_text)
        self.assertNotIn("{{today", message.received_at)


if __name__ == "__main__":
    unittest.main()
