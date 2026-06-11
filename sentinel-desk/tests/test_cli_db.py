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


class CliDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name

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
