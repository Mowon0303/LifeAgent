from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sentineldesk import db
from sentineldesk.cli import main
from sentineldesk.config import get_paths
from sentineldesk.daily import build_daily_landing_summary


class CliDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.sample_emails = Path(__file__).resolve().parents[1] / "fixtures" / "ui" / "sample_emails.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_init_creates_database_and_config(self) -> None:
        code = main(["--home", self.home, "init"])
        paths = get_paths(self.home)
        self.assertEqual(code, 0)
        self.assertTrue(paths.config.exists())
        self.assertTrue(paths.database.exists())

    def test_demo_seed_creates_targets(self) -> None:
        self.assertEqual(main(["--home", self.home, "demo", "seed"]), 0)
        targets = db.list_targets(get_paths(self.home))
        self.assertEqual(len(targets), 3)
        self.assertTrue(all(target["high_stakes"] for target in targets))
        self.assertTrue(any(target["kind"] == "lease" for target in targets))

    def test_demo_record_prep_creates_recording_state(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--home", self.home, "demo", "record-prep", "--port", "8899"])
        self.assertEqual(code, 0)
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["dashboard_url"], "http://127.0.0.1:8899/")
        self.assertEqual(summary["calendar_dashboard_url"], "http://127.0.0.1:8899/")
        self.assertEqual(summary["ops_dashboard_url"], "http://127.0.0.1:8899/ops")
        self.assertEqual(summary["run_count"], 5)
        self.assertEqual(summary["alert_count"], 2)
        self.assertEqual(summary["email_fixture"], "fixtures/ui/sample_emails.json")
        self.assertEqual(summary["email_messages_persisted"], 4)
        self.assertGreaterEqual(summary["email_facts_extracted"], 6)
        self.assertGreaterEqual(summary["calendar_draft_count"], 3)
        self.assertGreaterEqual(summary["task_count"], 3)
        self.assertEqual(len(summary["baseline_run_ids"]), 3)
        self.assertIn("email_calendar", summary["expected_states"])
        self.assertIn("baseline", summary["expected_states"])
        self.assertIn("critical", summary["expected_states"])
        self.assertIn("uncertain", summary["expected_states"])
        self.assertTrue(Path(summary["critical_report"]).exists())
        self.assertTrue(Path(summary["uncertain_report"]).exists())
        self.assertTrue(Path(summary["packages"]["critical"]).exists())
        self.assertTrue(Path(summary["packages"]["uncertain"]).exists())

    def test_daily_run_ingests_local_email_and_summarizes_landing_queue(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--home", self.home, "daily", "run", "--email-json", str(self.sample_emails)])
        self.assertEqual(code, 0)
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["status"], "ready")
        self.assertEqual(summary["mode"], "daily_landing")
        self.assertEqual(summary["sync"]["mode"], "local_json")
        self.assertFalse(summary["sync"]["external_network"])
        self.assertEqual(summary["sync"]["messages_persisted"], 4)
        self.assertEqual(summary["sync"]["deadline_events_drafted"], 3)
        self.assertEqual(summary["email"]["fact_counts"]["deadline"], 3)
        self.assertGreaterEqual(summary["tasks"]["queue_count"], 3)
        self.assertEqual(summary["calendar"]["pending_count"], 3)
        self.assertFalse(summary["safety"]["external_writes_performed"])
        self.assertTrue(summary["safety"]["calendar_writes_require_confirmation"])
        self.assertTrue(any(action["kind"] == "review_tasks" for action in summary["next_actions"]))
        events = db.list_audit_events(get_paths(self.home), limit=5)
        self.assertEqual(events[0]["action"], "daily.run")
        self.assertEqual(events[0]["metadata"]["sync_mode"], "local_json")

    def test_daily_run_uses_stored_only_state_without_refresh(self) -> None:
        self.assertEqual(main(["--home", self.home, "email", "scan", "--json", str(self.sample_emails)]), 0)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--home", self.home, "daily", "run", "--task-limit", "2", "--calendar-limit", "2"])
        self.assertEqual(code, 0)
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["sync"]["mode"], "stored_only")
        self.assertFalse(summary["sync"]["external_network"])
        self.assertEqual(summary["email"]["stored_message_count"], 4)
        self.assertEqual(len(summary["tasks"]["queue"]), 2)
        self.assertEqual(len(summary["calendar"]["items"]), 2)
        self.assertTrue(any(action["kind"] == "refresh" for action in summary["next_actions"]))

    def test_daily_run_redacts_connector_account_and_cursor(self) -> None:
        paths = get_paths(self.home)
        db.init_db(paths)
        db.upsert_connector_state(
            paths,
            connector="gmail_api",
            account_id="student.private@example.com",
            cursor="history-secret-123",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            metadata={"source_type": "gmail_api", "trust_label": "gmail_readonly"},
            updated_at="2026-06-12T00:00:00+00:00",
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--home", self.home, "daily", "run"])
        self.assertEqual(code, 0)
        raw = output.getvalue()
        summary = json.loads(raw)
        self.assertEqual(summary["connectors"][0]["account_id"], "[REDACTED_CONNECTOR_METADATA]")
        self.assertTrue(summary["connectors"][0]["has_cursor"])
        self.assertNotIn("student.private@example.com", raw)
        self.assertNotIn("history-secret-123", raw)

    def test_daily_summary_redacts_sync_account_and_cursor(self) -> None:
        paths = get_paths(self.home)
        db.init_db(paths)
        summary = build_daily_landing_summary(
            paths,
            sync_summary={
                "mode": "gmail_readonly",
                "external_network": True,
                "account_id": "student.private@example.com",
                "cursor": "history-secret-123",
                "cursor_saved": True,
            },
        )
        raw = json.dumps(summary)
        self.assertEqual(summary["sync"]["account_id"], "[REDACTED_CONNECTOR_METADATA]")
        self.assertEqual(summary["sync"]["cursor"], "[REDACTED_CONNECTOR_METADATA]")
        self.assertNotIn("student.private@example.com", raw)
        self.assertNotIn("history-secret-123", raw)

    def test_daily_run_rejects_multiple_refresh_sources(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(
                [
                    "--home",
                    self.home,
                    "daily",
                    "run",
                    "--email-json",
                    str(self.sample_emails),
                    "--sync-gmail",
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn("Use either --email-json or --sync-gmail", json.loads(output.getvalue())["error"])

    def test_watch_add_registers_target(self) -> None:
        self.assertEqual(main(["--home", self.home, "init"]), 0)
        self.assertEqual(main(["--home", self.home, "watch", "add", "--name", "x", "--url", "file:///tmp/x.html"]), 0)
        target = db.get_target(get_paths(self.home), name="x")
        self.assertIsNotNone(target)

    def test_doctor_fails_before_init(self) -> None:
        self.assertEqual(main(["--home", self.home, "doctor"]), 1)

    def test_doctor_passes_after_init(self) -> None:
        main(["--home", self.home, "init"])
        self.assertEqual(main(["--home", self.home, "doctor"]), 0)

    def test_module_entrypoint_preserves_cli_exit_code(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", "-m", "sentineldesk", "--home", self.home, "doctor"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn('"ok": false', result.stdout)


if __name__ == "__main__":
    unittest.main()
