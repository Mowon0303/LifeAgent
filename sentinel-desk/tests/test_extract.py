from __future__ import annotations

import unittest
from pathlib import Path

from sentineldesk.config import project_root
from sentineldesk.extract import detect_health, extract_deadlines, extract_page, extract_status, normalize_text, stable_hash, visible_text


FIXTURES = project_root() / "fixtures" / "portals"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class ExtractTests(unittest.TestCase):
    def test_visible_text_removes_markup(self) -> None:
        title, text = visible_text("<html><title>T</title><body><h1>Hello</h1><script>bad()</script><p>World</p></body></html>")
        self.assertEqual(title, "T")
        self.assertIn("Hello", text)
        self.assertNotIn("bad", text)

    def test_normalize_text_collapses_whitespace(self) -> None:
        self.assertEqual(normalize_text(" a\n\n b\t c "), "a b c")

    def test_stable_hash_ignores_spacing(self) -> None:
        self.assertEqual(stable_hash("a b c"), stable_hash("a\n b\tc"))

    def test_extract_submitted_status(self) -> None:
        status = extract_status(fixture("opt_submitted.html"))
        self.assertEqual(status["value"], "submitted")
        self.assertGreater(status["confidence"], 0.8)

    def test_extract_action_required_status(self) -> None:
        status = extract_status(fixture("opt_action_required.html"))
        self.assertEqual(status["value"], "action_required")

    def test_extract_approved_status(self) -> None:
        status = extract_status(fixture("opt_approved.html"))
        self.assertEqual(status["value"], "approved")

    def test_extract_appointment_slot_status(self) -> None:
        status = extract_status(fixture("appointment_available.html"))
        self.assertEqual(status["value"], "action_required")

    def test_extract_lease_current_status(self) -> None:
        status = extract_status(fixture("lease_current.html"))
        self.assertEqual(status["value"], "current")

    def test_extract_lease_notice_required_status(self) -> None:
        status = extract_status(fixture("lease_notice_required.html"))
        self.assertEqual(status["value"], "action_required")

    def test_extract_lease_rent_due_status(self) -> None:
        status = extract_status(fixture("lease_rent_due.html"))
        self.assertEqual(status["value"], "action_required")

    def test_extract_unknown_status(self) -> None:
        status = extract_status(fixture("redesign_unknown.html"))
        self.assertEqual(status["value"], "unknown")

    def test_extract_deadline_iso_date(self) -> None:
        deadlines = extract_deadlines(fixture("opt_action_required.html"))
        self.assertTrue(any(item["date_text"] == "June 28, 2026" for item in deadlines))

    def test_extract_deadline_slash_date(self) -> None:
        deadlines = extract_deadlines(fixture("appointment_none.html"))
        self.assertTrue(any(item["date_text"] == "06/30/2026" for item in deadlines))

    def test_extract_lease_notice_deadline(self) -> None:
        deadlines = extract_deadlines(fixture("lease_notice_required.html"))
        self.assertTrue(any(item["date_text"] == "July 15, 2026" for item in deadlines))

    def test_extract_lease_rent_due_deadline(self) -> None:
        deadlines = extract_deadlines(fixture("lease_rent_due.html"))
        self.assertTrue(any(item["date_text"] == "06/05/2026" for item in deadlines))

    def test_ok_health_for_portal_page(self) -> None:
        health = detect_health(fixture("opt_submitted.html"))
        self.assertEqual(health["state"], "ok")

    def test_session_expired_is_uncertain(self) -> None:
        health = detect_health(fixture("session_expired.html"))
        self.assertEqual(health["state"], "uncertain")
        self.assertTrue(any("login_required" in reason for reason in health["reasons"]))

    def test_captcha_is_uncertain(self) -> None:
        health = detect_health(fixture("captcha_block.html"))
        self.assertEqual(health["state"], "uncertain")
        self.assertTrue(any("bot_blocked" in reason for reason in health["reasons"]))

    def test_maintenance_is_uncertain(self) -> None:
        health = detect_health(fixture("portal_maintenance.html"))
        self.assertEqual(health["state"], "uncertain")
        self.assertTrue(any("server_error" in reason for reason in health["reasons"]))

    def test_short_page_is_uncertain(self) -> None:
        health = detect_health("OK")
        self.assertEqual(health["state"], "uncertain")

    def test_extract_page_contract(self) -> None:
        extraction = extract_page(fixture("opt_submitted.html"))
        self.assertIn("OPT Case Portal", extraction.title)
        self.assertEqual(extraction.health["state"], "ok")
        self.assertEqual(extraction.status["value"], "submitted")
        self.assertTrue(extraction.text_hash)


if __name__ == "__main__":
    unittest.main()
