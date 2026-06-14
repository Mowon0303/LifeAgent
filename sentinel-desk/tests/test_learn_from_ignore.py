from __future__ import annotations

import tempfile
import unittest

from sentineldesk import db
from sentineldesk.config import get_paths
from sentineldesk.email.models import EmailMessage
from sentineldesk.tasks import list_tasks, review_task


def _action_fact(source_id: str) -> dict:
    return {
        "kind": "action",
        "value": "confirm your subscription",
        "source_id": source_id,
        "source_type": "email",
        "trust_label": "email_unverified",
        "evidence": "Please confirm your subscription.",
        "confidence": 0.6,
        "received_at": "2026-06-10T00:00:00Z",
        "metadata": {},
    }


def _seed(paths, message_id: str, sender: str) -> None:
    message = EmailMessage(
        message_id=message_id,
        thread_id=f"t-{message_id}",
        sender=sender,
        subject="Newsletter",
        received_at="2026-06-10T00:00:00Z",
        body_text="Please confirm your subscription.",
    )
    db.upsert_email_message(
        paths, message=message, facts=[_action_fact(f"email:{message_id}")],
        ingested_at="2026-06-10T12:00:00Z",
    )


class LearnFromIgnoreTests(unittest.TestCase):
    def test_repeatedly_ignored_sender_is_auto_muted(self) -> None:
        sender = "Junk Mail <promos@junk.example>"
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            db.init_db(paths)
            # Three messages from the same sender, all ignored by the reviewer.
            for i in range(3):
                _seed(paths, f"m-junk-{i}", sender)
            for task in list_tasks(paths, today="2026-06-10"):
                if task["sender"] == sender:
                    review_task(
                        paths, task_id=task["task_id"], status="ignored",
                        note="", actor="tester", updated_at="2026-06-10T13:00:00Z",
                    )

            # A new message from the same sender arrives.
            _seed(paths, "m-junk-3", sender)
            # ... and a message from a different sender that must NOT be muted.
            _seed(paths, "m-real", "Landlord <leasing@property.example>")

            tasks = {t["task_id"]: t for t in list_tasks(paths, today="2026-06-10")}
            new_junk = [t for t in tasks.values() if t["sender"] == sender and t["status"] == "new"]
            other = [t for t in tasks.values() if "property.example" in t["sender"]]

            self.assertTrue(new_junk)
            self.assertTrue(all(t["muted"] for t in new_junk))
            self.assertTrue(all(t["priority_band"] == "low" for t in new_junk))
            self.assertTrue(all("muted_sender" in t["priority_reasons"] for t in new_junk))
            # an unrelated sender is untouched
            self.assertTrue(other)
            self.assertTrue(all(not t["muted"] for t in other))

    def test_below_threshold_sender_is_not_muted(self) -> None:
        sender = "Maybe <hello@sometimes.example>"
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            db.init_db(paths)
            for i in range(2):  # only two ignores — below the threshold of 3
                _seed(paths, f"m-x-{i}", sender)
            for task in list_tasks(paths, today="2026-06-10"):
                if task["sender"] == sender:
                    review_task(paths, task_id=task["task_id"], status="ignored",
                                note="", actor="t", updated_at="2026-06-10T13:00:00Z")
            _seed(paths, "m-x-3", sender)

            new_tasks = [t for t in list_tasks(paths, today="2026-06-10") if t["sender"] == sender and t["status"] == "new"]
            self.assertTrue(new_tasks)
            self.assertTrue(all(not t["muted"] for t in new_tasks))


if __name__ == "__main__":
    unittest.main()
