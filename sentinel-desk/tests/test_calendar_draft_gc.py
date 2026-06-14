from __future__ import annotations

import tempfile
import unittest

from sentineldesk import db
from sentineldesk.calendar.models import DeadlineEvent
from sentineldesk.config import get_paths
from sentineldesk.email.ingest import reprocess_stored_messages
from sentineldesk.email.models import EmailMessage


def _promo_with_bare_date() -> EmailMessage:
    # Promotions tab + a bare date and no obligation: the category gate drops
    # the deadline, so re-extraction produces no draft for this message.
    return EmailMessage(
        message_id="m-promo",
        thread_id="t-promo",
        sender="news@shop.example",
        subject="Weekly digest",
        received_at="2026-06-01T00:00:00Z",
        body_text="Browse our new arrivals. Posted Jun 4, 2026. View online.",
        source_type="gmail",
        trust_label="email_provider_api",
        labels=("CATEGORY_PROMOTIONS",),
    )


def _real_deadline_message() -> EmailMessage:
    return EmailMessage(
        message_id="m-real",
        thread_id="t-real",
        sender="leasing@example.com",
        subject="Renewal paperwork",
        received_at="2026-06-01T00:00:00Z",
        body_text="Please respond by July 1, 2026 to keep your unit.",
        source_type="gmail",
        trust_label="email_provider_api",
        labels=("INBOX", "CATEGORY_PERSONAL"),
    )


class CalendarDraftGCTests(unittest.TestCase):
    def test_reprocess_removes_orphan_local_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            db.init_db(paths)
            msg = _promo_with_bare_date()
            db.upsert_email_message(paths, message=msg, facts=[], ingested_at="2026-06-01T00:00:00Z")
            stale = DeadlineEvent(
                title="Weekly digest",
                date_text="Jun 4, 2026",
                source_ids=(msg.source_id,),
                evidence_uri=msg.source_id,
            )
            db.upsert_calendar_draft(paths, event=stale, created_at="2026-06-01T00:00:00Z", sync_state="local_draft")
            self.assertEqual(len(db.list_calendar_drafts(paths)), 1)

            result = reprocess_stored_messages(paths, limit=500)

            self.assertEqual(result["stale_drafts_removed"], 1)
            self.assertEqual(db.list_calendar_drafts(paths), [])

    def test_reprocess_keeps_a_live_deadline_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            db.init_db(paths)
            msg = _real_deadline_message()
            db.upsert_email_message(paths, message=msg, facts=[], ingested_at="2026-06-01T00:00:00Z")

            result = reprocess_stored_messages(paths, limit=500)

            self.assertEqual(result["stale_drafts_removed"], 0)
            drafts = db.list_calendar_drafts(paths)
            self.assertEqual(len(drafts), 1)
            self.assertEqual(drafts[0]["date_text"], "July 1, 2026")

    def test_reprocess_never_deletes_a_confirmed_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            db.init_db(paths)
            # A confirmed/synced draft with no backing message — GC must leave it.
            confirmed = DeadlineEvent(
                title="Confirmed appointment",
                date_text="July 9, 2026",
                source_ids=("gmail:gone",),
                evidence_uri="gmail:gone",
            )
            db.upsert_calendar_draft(paths, event=confirmed, created_at="2026-06-01T00:00:00Z", sync_state="synced")

            result = reprocess_stored_messages(paths, limit=500)

            self.assertEqual(result["stale_drafts_removed"], 0)
            self.assertEqual(len(db.list_calendar_drafts(paths)), 1)

    def test_truncated_pass_does_not_garbage_collect(self) -> None:
        """When the reprocess window is smaller than the corpus we cannot prove a
        draft is stale, so GC is skipped rather than risk deleting a valid one."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            db.init_db(paths)
            for i in range(3):
                msg = _promo_with_bare_date()
                object.__setattr__(msg, "message_id", f"m-promo-{i}")
                db.upsert_email_message(paths, message=msg, facts=[], ingested_at="2026-06-01T00:00:00Z")
            stale = DeadlineEvent(title="x", date_text="Jun 4, 2026", source_ids=("gmail:m-promo-0",), evidence_uri="gmail:m-promo-0")
            db.upsert_calendar_draft(paths, event=stale, created_at="2026-06-01T00:00:00Z", sync_state="local_draft")

            result = reprocess_stored_messages(paths, limit=2)  # smaller than 3 stored

            self.assertEqual(result["stale_drafts_removed"], 0)
            self.assertEqual(len(db.list_calendar_drafts(paths)), 1)


if __name__ == "__main__":
    unittest.main()
