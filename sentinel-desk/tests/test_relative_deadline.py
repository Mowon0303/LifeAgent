from __future__ import annotations

import datetime as dt
import unittest

from sentineldesk.calendar.draft import draft_events_from_facts
from sentineldesk.email.extract import extract_email_facts
from sentineldesk.email.models import EmailMessage
from sentineldesk.extract import resolve_relative_deadline


class ResolveRelativeDeadlineTests(unittest.TestCase):
    def test_within_n_days_anchors_to_receipt_date(self) -> None:
        self.assertEqual(
            resolve_relative_deadline("within 10 days", "2026-06-01T00:00:00Z"),
            "2026-06-11",
        )

    def test_external_anchor_is_not_resolved(self) -> None:
        # "within 30 days of your program end date" — anchored to graduation, not
        # the email. Must stay unresolved so we don't invent a date.
        self.assertIsNone(
            resolve_relative_deadline(
                "within 30 days",
                "2026-06-01T00:00:00Z",
                context="You must apply within 30 days of your program end date.",
            )
        )

    def test_end_of_month(self) -> None:
        self.assertEqual(
            resolve_relative_deadline("by the end of the month", "2026-06-13T00:00:00Z"),
            "2026-06-30",
        )

    def test_next_weekday_is_upcoming_and_correct_dow(self) -> None:
        result = resolve_relative_deadline("next Friday", "2026-06-15T00:00:00Z")
        self.assertIsNotNone(result)
        resolved = dt.date.fromisoformat(result)
        self.assertEqual(resolved.weekday(), 4)  # Friday
        self.assertGreater(resolved, dt.date(2026, 6, 15))

    def test_business_days_skip_weekends(self) -> None:
        # 2026-06-01 is a Monday; +5 business days lands on the next Monday.
        self.assertEqual(
            resolve_relative_deadline("within 5 business days", "2026-06-01T00:00:00Z"),
            "2026-06-08",
        )

    def test_absolute_date_is_left_alone(self) -> None:
        self.assertIsNone(resolve_relative_deadline("July 1, 2026", "2026-06-01T00:00:00Z"))

    def test_rfc2822_receipt_date_is_parsed(self) -> None:
        self.assertEqual(
            resolve_relative_deadline("within 7 days", "Thu, 4 Jun 2026 09:08:00 -0700"),
            "2026-06-11",
        )


class RelativeDeadlineDraftTests(unittest.TestCase):
    """Extraction stays faithful to the email text (the phrase); the calendar
    draft layer is where a from-now relative deadline gets a computed date."""

    def _pipeline(self, body: str, received_at: str = "2026-06-01T00:00:00Z"):
        message = EmailMessage(
            message_id="m1", thread_id="t1", sender="registrar@school.edu",
            subject="Action needed", received_at=received_at, body_text=body,
        )
        facts = [f for f in extract_email_facts(message) if f.kind == "deadline"]
        events = draft_events_from_facts(facts, evidence_uri=message.source_id).events
        return facts, events

    def test_relative_deadline_drafts_a_dated_estimate(self) -> None:
        facts, events = self._pipeline("You must respond within 10 days to keep your status.")
        # the fact keeps the literal phrase (extraction is not invented)
        self.assertTrue(any(f.value == "within 10 days" for f in facts))
        # but the calendar draft carries a computed date, kept uncertain
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].date_text, "2026-06-11")
        self.assertLess(events[0].confidence, 0.8)

    def test_external_anchor_relative_deadline_is_not_drafted(self) -> None:
        facts, events = self._pipeline("You must apply within 30 days of your program end date.")
        # surfaced as a review task, but never offered as a dated calendar event
        self.assertTrue(facts)
        self.assertEqual(events, ())


if __name__ == "__main__":
    unittest.main()
