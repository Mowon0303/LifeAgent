from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from sentineldesk import db
from sentineldesk.cli import main
from sentineldesk.config import get_paths
from sentineldesk.daily import build_daily_landing_summary
from sentineldesk.integrations.google_workspace import GMAIL_READONLY_SCOPE
from sentineldesk.secrets import SecretUnavailable


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

    def test_acceptance_first_run_prepares_and_verifies_local_mvp(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--home", self.home, "acceptance", "first-run", "--port", "8898"])
        raw = output.getvalue()
        summary = json.loads(raw)
        self.assertEqual(code, 0)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["mode"], "first_run_acceptance")
        self.assertFalse(summary["external_network"])
        self.assertFalse(summary["external_writes_performed"])
        self.assertEqual(summary["dashboard"]["calendar_url"], "http://127.0.0.1:8898/")
        self.assertEqual(summary["summary"]["stored_messages"], 4)
        self.assertEqual(summary["summary"]["fact_counts"]["deadline"], 3)
        self.assertEqual(summary["summary"]["task_queue_count"], 7)
        self.assertEqual(summary["summary"]["calendar_pending_count"], 3)
        self.assertIn("2026-07-01", summary["summary"]["calendar_dates"])
        self.assertEqual(summary["summary"]["gmail_readiness_status"], "needs_oauth")
        self.assertEqual(summary["ask_smoke"]["intent"], "latest_deadline")
        self.assertIn("search_latest_email", summary["ask_smoke"]["tool_calls"])
        self.assertGreaterEqual(summary["ask_smoke"]["citation_count"], 1)
        self.assertTrue(all(check["status"] == "passed" for check in summary["checks"]))
        self.assertNotIn(self.home, raw)

        second_output = io.StringIO()
        with contextlib.redirect_stdout(second_output):
            second_code = main(["--home", self.home, "acceptance", "first-run"])
        self.assertEqual(second_code, 0)
        self.assertEqual(json.loads(second_output.getvalue())["status"], "passed")

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

    def test_integrations_gmail_readiness_cli_reports_oauth_next_action(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(
                [
                    "--home",
                    self.home,
                    "integrations",
                    "gmail-readiness",
                    "--account",
                    "student.private@example.com",
                    "--google-credentials-env",
                    "SENTINEL_TEST_MISSING_GOOGLE_CREDS",
                    "--google-token-env",
                    "SENTINEL_TEST_MISSING_GOOGLE_TOKEN",
                ]
            )
        raw = output.getvalue()
        payload = json.loads(raw)
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "needs_oauth")
        self.assertEqual(payload["next_action"]["kind"], "configure_google_credentials")
        self.assertFalse(payload["external_network"])
        self.assertFalse(payload["external_writes_performed"])
        self.assertNotIn("student.private@example.com", raw)

    def test_email_sync_gmail_failure_writes_redacted_diagnostics(self) -> None:
        class FailingFactory:
            def __init__(self, config: object) -> None:
                self.config = config

            def gmail_client(self) -> object:
                raise SecretUnavailable("Missing required environment secret: SENTINEL_TEST_GOOGLE_TOKEN")

        output = io.StringIO()
        with mock.patch("sentineldesk.gmail_sync.GoogleWorkspaceFactory", FailingFactory), contextlib.redirect_stdout(output):
            code = main(
                [
                    "--home",
                    self.home,
                    "email",
                    "sync-gmail",
                    "--account",
                    "student.private@example.com",
                    "--query",
                    "deadline",
                ]
            )
        raw = output.getvalue()
        payload = json.loads(raw)
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "gmail_sync_failed")
        self.assertEqual(payload["diagnostics"]["status"], "failed")
        self.assertEqual(payload["diagnostics"]["latest_failure"]["category"], "missing_secret")
        self.assertEqual(payload["diagnostics"]["next_action"]["kind"], "check_gmail_readiness")
        self.assertFalse(payload["diagnostics"]["external_network"])
        self.assertFalse(payload["diagnostics"]["external_writes_performed"])
        self.assertNotIn("student.private@example.com", raw)
        self.assertNotIn("SENTINEL_TEST_GOOGLE_TOKEN", raw)
        events = db.list_audit_events(get_paths(self.home), limit=5)
        self.assertEqual(events[0]["action"], "email.connector.sync.failed")
        self.assertFalse(events[0]["allowed"])
        self.assertFalse(events[0]["metadata"]["raw_error_included"])
        diagnostics_output = io.StringIO()
        with contextlib.redirect_stdout(diagnostics_output):
            diagnostics_code = main(["--home", self.home, "integrations", "gmail-sync-diagnostics"])
        self.assertEqual(diagnostics_code, 0)
        diagnostics = json.loads(diagnostics_output.getvalue())
        self.assertEqual(diagnostics["status"], "failed")
        self.assertEqual(diagnostics["latest_failure"]["category"], "missing_secret")

    def test_daily_sync_gmail_failure_returns_summary_and_diagnostics(self) -> None:
        class FailingFactory:
            def __init__(self, config: object) -> None:
                self.config = config

            def gmail_client(self) -> object:
                raise RuntimeError("403 insufficientPermissions token-secret")

        output = io.StringIO()
        with mock.patch("sentineldesk.gmail_sync.GoogleWorkspaceFactory", FailingFactory), contextlib.redirect_stdout(output):
            code = main(["--home", self.home, "daily", "run", "--sync-gmail", "--account", "student.private@example.com"])
        raw = output.getvalue()
        payload = json.loads(raw)
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "gmail_sync_failed")
        self.assertEqual(payload["diagnostics"]["latest_failure"]["category"], "permission_denied")
        self.assertEqual(payload["daily_summary"]["gmail_sync_diagnostics"]["status"], "failed")
        self.assertFalse(payload["daily_summary"]["safety"]["local_audit_written"])
        self.assertNotIn("student.private@example.com", raw)
        self.assertNotIn("token-secret", raw)

    def test_daily_summary_embeds_ready_gmail_readiness_without_secret_values(self) -> None:
        paths = get_paths(self.home)
        self.assertEqual(main(["--home", self.home, "email", "scan", "--json", str(self.sample_emails)]), 0)
        db.upsert_connector_state(
            paths,
            connector="gmail_api",
            account_id="student.private@example.com",
            cursor="history-secret-123",
            scopes=[GMAIL_READONLY_SCOPE],
            metadata={"source_type": "gmail_api", "trust_label": "gmail_readonly"},
            updated_at="2026-06-12T00:00:00+00:00",
        )
        env = {
            "SENTINEL_TEST_GOOGLE_CREDS": json.dumps({"installed": {"client_id": "client-id-test", "client_secret": "client-secret-test"}}),
            "SENTINEL_TEST_GOOGLE_TOKEN": json.dumps({"refresh_token": "refresh-token-test", "scopes": [GMAIL_READONLY_SCOPE]}),
        }
        ready_dependency = {
            "name": "gmail.dependencies",
            "status": "ready",
            "detail": "Gmail optional dependencies are importable.",
            "metadata": {"required_modules": [], "missing_modules": []},
        }
        with mock.patch.dict(os.environ, env, clear=False), mock.patch(
            "sentineldesk.gmail_readiness._dependency_check",
            return_value=ready_dependency,
        ):
            summary = build_daily_landing_summary(
                paths,
                account_id="student.private@example.com",
                google_credentials_env="SENTINEL_TEST_GOOGLE_CREDS",
                google_token_env="SENTINEL_TEST_GOOGLE_TOKEN",
                record_audit=False,
            )
        raw = json.dumps(summary)
        readiness = summary["gmail_readiness"]
        self.assertEqual(readiness["status"], "ready")
        self.assertTrue(readiness["oauth_ready"])
        self.assertTrue(readiness["has_cursor"])
        self.assertTrue(readiness["has_local_evidence"])
        self.assertEqual(readiness["next_action"]["kind"], "review_tasks")
        self.assertNotIn("student.private@example.com", raw)
        self.assertNotIn("history-secret-123", raw)
        self.assertNotIn("client-secret-test", raw)
        self.assertNotIn("refresh-token-test", raw)

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
