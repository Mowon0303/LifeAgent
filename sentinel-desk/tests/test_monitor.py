from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sentineldesk import db
from sentineldesk.cdp import CDPCapture
from sentineldesk.config import ensure_dirs, file_url, get_paths, project_root
from sentineldesk.extract import utc_now
from sentineldesk.monitor import classify_run, run_target


FIXTURES = project_root() / "fixtures" / "portals"


class MonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = get_paths(self.tmp.name)
        ensure_dirs(self.paths)
        db.init_db(self.paths)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def add_target(self, fixture_name: str, high_stakes: bool = True) -> dict:
        db.upsert_target(
            self.paths,
            name="case",
            url=file_url(FIXTURES / fixture_name),
            kind="opt",
            high_stakes=high_stakes,
            created_at=utc_now(),
        )
        target = db.get_target(self.paths, name="case")
        assert target is not None
        return target

    def update_target_url(self, fixture_name: str) -> dict:
        db.upsert_target(
            self.paths,
            name="case",
            url=file_url(FIXTURES / fixture_name),
            kind="opt",
            high_stakes=True,
            created_at=utc_now(),
        )
        target = db.get_target(self.paths, name="case")
        assert target is not None
        return target

    def test_first_run_is_baseline(self) -> None:
        run = run_target(self.paths, self.add_target("opt_submitted.html"))
        self.assertEqual(run["alert"]["level"], "baseline")
        self.assertEqual(run["status"]["value"], "submitted")

    def test_same_page_has_no_alert(self) -> None:
        target = self.add_target("opt_submitted.html")
        run_target(self.paths, target)
        run = run_target(self.paths, self.update_target_url("opt_submitted.html"))
        self.assertEqual(run["alert"]["level"], "none")
        self.assertEqual(run["diff"]["kind"], "no_change")

    def test_action_required_is_critical(self) -> None:
        run_target(self.paths, self.add_target("opt_submitted.html"))
        run = run_target(self.paths, self.update_target_url("opt_action_required.html"))
        self.assertEqual(run["alert"]["level"], "critical")
        self.assertEqual(run["status"]["value"], "action_required")
        self.assertTrue(run["diff"]["status_changed"])

    def test_approved_status_change_is_critical(self) -> None:
        run_target(self.paths, self.add_target("opt_submitted.html"))
        run = run_target(self.paths, self.update_target_url("opt_approved.html"))
        self.assertEqual(run["alert"]["level"], "critical")
        self.assertEqual(run["status"]["value"], "approved")

    def test_deadline_change_is_critical(self) -> None:
        run_target(self.paths, self.add_target("appointment_none.html"))
        run = run_target(self.paths, self.update_target_url("appointment_available.html"))
        self.assertEqual(run["alert"]["level"], "critical")
        self.assertTrue(run["diff"]["deadline_changed"])

    def test_session_expired_fails_loud(self) -> None:
        run_target(self.paths, self.add_target("opt_submitted.html"))
        run = run_target(self.paths, self.update_target_url("session_expired.html"))
        self.assertEqual(run["alert"]["level"], "uncertain")
        self.assertTrue(run["alert"]["fail_loud"])

    def test_captcha_fails_loud(self) -> None:
        run_target(self.paths, self.add_target("appointment_none.html"))
        run = run_target(self.paths, self.update_target_url("captcha_block.html"))
        self.assertEqual(run["alert"]["level"], "uncertain")
        self.assertIn("Cannot verify", run["alert"]["reason"])

    def test_maintenance_fails_loud(self) -> None:
        run_target(self.paths, self.add_target("opt_submitted.html"))
        run = run_target(self.paths, self.update_target_url("portal_maintenance.html"))
        self.assertEqual(run["alert"]["level"], "uncertain")
        self.assertTrue(run["alert"]["fail_loud"])

    def test_unknown_status_fails_loud_for_high_stakes(self) -> None:
        run = run_target(self.paths, self.add_target("redesign_unknown.html"))
        self.assertEqual(run["alert"]["level"], "uncertain")
        self.assertEqual(run["diff"]["kind"], "unknown_status")
        self.assertIn("OPT/USCIS/OIS", run["alert"]["reason"])

    def test_unknown_status_can_baseline_for_low_stakes(self) -> None:
        run = run_target(self.paths, self.add_target("redesign_unknown.html", high_stakes=False))
        self.assertEqual(run["alert"]["level"], "baseline")

    def test_irrelevant_text_change_is_info(self) -> None:
        run_target(self.paths, self.add_target("opt_submitted.html"))
        run = run_target(self.paths, self.update_target_url("irrelevant_copy_change.html"))
        self.assertEqual(run["alert"]["level"], "info")
        self.assertEqual(run["diff"]["kind"], "irrelevant_or_unclassified_change")

    def test_evidence_bundle_is_written(self) -> None:
        run = run_target(self.paths, self.add_target("opt_submitted.html"))
        evidence_path = Path(run["evidence"]["path"])
        self.assertTrue(evidence_path.exists())
        self.assertIn("after_text_preview", evidence_path.read_text(encoding="utf-8"))

    def test_redacted_evidence_bundle_is_written(self) -> None:
        target = self.add_target("opt_submitted.html")
        target["url"] = file_url(FIXTURES / "opt_submitted.html") + "?email=a@example.com"
        run = run_target(self.paths, target)
        redacted_path = Path(run["evidence"]["redacted_path"])
        self.assertTrue(redacted_path.exists())
        payload = redacted_path.read_text(encoding="utf-8")
        self.assertIn("[REDACTED_URL]", payload)
        self.assertNotIn("a@example.com", payload)

    def test_cdp_screenshot_is_written_to_run_artifacts(self) -> None:
        html = """<!doctype html>
<html>
  <head><title>OPT Portal</title></head>
  <body>
    <h1>USCIS OPT Case</h1>
    <p>Case received and application received by the portal.</p>
    <p>Receipt A1234567890. Next deadline June 10, 2026.</p>
  </body>
</html>
"""
        db.upsert_target(
            self.paths,
            name="cdp-case",
            url="cdp://127.0.0.1:9222/current?id=target-1",
            kind="opt",
            high_stakes=True,
            created_at=utc_now(),
        )
        target = db.get_target(self.paths, name="cdp-case")
        assert target is not None
        png = b"\x89PNG\r\n\x1a\nfake"
        with patch("sentineldesk.monitor.capture_from_url", return_value=CDPCapture(html=html, final_url="https://example.edu/portal", screenshot=png)):
            run = run_target(self.paths, target)

        screenshot_path = Path(str(run["screenshot_path"]))
        self.assertTrue(screenshot_path.exists())
        self.assertEqual(screenshot_path.read_bytes(), png)
        evidence = json.loads(Path(run["evidence"]["path"]).read_text(encoding="utf-8"))
        self.assertEqual(evidence["artifacts"]["screenshot_path"], str(screenshot_path))

    def test_shareable_report_is_written(self) -> None:
        run = run_target(self.paths, self.add_target("opt_submitted.html"))
        report_path = Path(run["evidence"]["report_path"])
        self.assertTrue(report_path.exists())
        self.assertIn("SentinelDesk Evidence Report", report_path.read_text(encoding="utf-8"))

    def test_trace_events_are_written(self) -> None:
        run = run_target(self.paths, self.add_target("opt_submitted.html"))
        traces = db.list_traces(self.paths, run["run_id"])
        self.assertGreaterEqual(len(traces), 3)

    def test_classify_without_previous_uncertain_health(self) -> None:
        diff, alert = classify_run(None, type("Fake", (), {
            "health": {"state": "uncertain", "reasons": ["login_required"], "confidence": 0.3},
            "status": {"value": "unknown", "confidence": 0.2},
            "deadlines": [],
            "text_hash": "abc",
        })(), True)
        self.assertEqual(diff["kind"], "uncertain_health")
        self.assertEqual(alert["level"], "uncertain")

    def test_capture_failure_records_uncertain_run(self) -> None:
        db.upsert_target(
            self.paths,
            name="bad",
            url="file:///tmp/does-not-exist-sentineldesk.html",
            kind="opt",
            high_stakes=True,
            created_at=utc_now(),
        )
        target = db.get_target(self.paths, name="bad")
        assert target is not None
        run = run_target(self.paths, target)
        self.assertEqual(run["alert"]["level"], "uncertain")
        evidence = json.loads(Path(run["evidence"]["path"]).read_text(encoding="utf-8"))
        self.assertIn("capture_error", evidence)


if __name__ == "__main__":
    unittest.main()
