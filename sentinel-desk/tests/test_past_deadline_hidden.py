from __future__ import annotations

import tempfile
import unittest

from sentineldesk import db
from sentineldesk.calendar.view import build_calendar_items
from sentineldesk.config import get_paths
from sentineldesk.email.models import EmailMessage
from sentineldesk.tasks import list_tasks

TODAY = "2026-06-13"


def _deadline_fact(source_id: str, value: str) -> dict:
    return {
        "kind": "deadline",
        "value": value,
        "source_id": source_id,
        "source_type": "email",
        "trust_label": "email_unverified",
        "evidence": f"due {value}",
        "confidence": 0.9,
        "received_at": "2026-01-01T00:00:00Z",
        "metadata": {},
    }


def _message(message_id: str) -> EmailMessage:
    return EmailMessage(
        message_id=message_id,
        thread_id=f"t-{message_id}",
        sender="billing@example.com",
        subject="Account notice",
        received_at="2026-01-01T00:00:00Z",
        body_text="See attached.",
    )


class PastDeadlineHiddenTests(unittest.TestCase):
    def test_list_tasks_hides_past_deadline_keeps_future_and_dateless(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            db.init_db(paths)
            db.upsert_email_message(
                paths, message=_message("m-past"),
                facts=[_deadline_fact("email:m-past", "May 1, 2026")],
                ingested_at="2026-01-01T00:00:00Z",
            )
            db.upsert_email_message(
                paths, message=_message("m-future"),
                facts=[_deadline_fact("email:m-future", "December 1, 2026")],
                ingested_at="2026-01-01T00:00:00Z",
            )
            db.upsert_email_message(
                paths, message=_message("m-relative"),
                facts=[_deadline_fact("email:m-relative", "within 30 days")],  # unparseable → kept
                ingested_at="2026-01-01T00:00:00Z",
            )

            tasks = list_tasks(paths, today=TODAY, limit=100)
            values = {task["value"] for task in tasks if task["kind"] == "deadline"}

            self.assertIn("December 1, 2026", values)
            self.assertIn("within 30 days", values)
            self.assertNotIn("May 1, 2026", values)

    def test_today_itself_is_not_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            db.init_db(paths)
            db.upsert_email_message(
                paths, message=_message("m-today"),
                facts=[_deadline_fact("email:m-today", "June 13, 2026")],
                ingested_at="2026-01-01T00:00:00Z",
            )
            values = {t["value"] for t in list_tasks(paths, today=TODAY) if t["kind"] == "deadline"}
            self.assertIn("June 13, 2026", values)

    def test_build_calendar_items_hides_past_draft_but_keeps_approved(self) -> None:
        drafts = [
            {"event_id": "e-past", "title": "old", "date_text": "May 1, 2026", "sync_state": "local_draft", "confidence": 0.9},
            {"event_id": "e-past-confirmed", "title": "kept", "date_text": "May 2, 2026", "sync_state": "synced", "confidence": 0.9},
            {"event_id": "e-future", "title": "future", "date_text": "December 1, 2026", "sync_state": "local_draft", "confidence": 0.9},
        ]
        items = build_calendar_items(drafts, [], today=TODAY)
        ids = {item["event_id"] for item in items}
        self.assertEqual(ids, {"e-past-confirmed", "e-future"})


if __name__ == "__main__":
    unittest.main()
