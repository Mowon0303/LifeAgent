from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest

from sentineldesk import db
from sentineldesk.cli import main
from sentineldesk.config import get_paths
from sentineldesk.email.ingest import ingest_messages
from sentineldesk.email.models import EmailMessage
from sentineldesk.tasks import list_tasks, review_task


def task_message() -> EmailMessage:
    return EmailMessage(
        message_id="m-task",
        thread_id="t-task",
        sender="leasing@example.com",
        subject="Move-out Notice Reminder",
        received_at="2026-06-10T09:00:00Z",
        body_text="Please submit written notice by July 2, 2026. Current balance due is $25.00.",
    )


class TaskReviewTests(unittest.TestCase):
    def test_list_tasks_merges_deadline_calendar_draft_and_email_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            ingest_messages(paths, [task_message()], ingested_at="2026-06-10T12:00:00Z")

            tasks = list_tasks(paths)
            kinds = [task["kind"] for task in tasks]

            self.assertEqual(kinds.count("deadline"), 1)
            self.assertIn("amount", kinds)
            self.assertIn("action", kinds)
            deadline = next(task for task in tasks if task["kind"] == "deadline")
            self.assertTrue(deadline["task_id"].startswith("calendar:"))
            self.assertEqual(deadline["status"], "new")
            self.assertEqual(deadline["source_refs"], ["email:m-task"])
            self.assertEqual(deadline["due_date"], "July 2, 2026")

    def test_review_task_persists_status_and_audit_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            ingest_messages(paths, [task_message()], ingested_at="2026-06-10T12:00:00Z")
            task_id = list_tasks(paths)[0]["task_id"]

            result = review_task(
                paths,
                task_id=task_id,
                status="needs_verification",
                note="Check portal before acting.",
                actor="tester",
                updated_at="2026-06-10T12:05:00Z",
            )

            self.assertEqual(result.status, "needs_verification")
            reviewed = next(task for task in list_tasks(paths) if task["task_id"] == task_id)
            self.assertEqual(reviewed["status"], "needs_verification")
            self.assertEqual(reviewed["review_note"], "Check portal before acting.")
            audit = db.list_audit_events(paths)[0]
            self.assertEqual(audit["action"], "task.review")
            self.assertEqual(audit["actor"], "tester")
            self.assertEqual(audit["subject"], task_id)
            self.assertEqual(audit["side_effect"], "local_db_write")

    def test_cli_tasks_list_and_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            ingest_messages(paths, [task_message()], ingested_at="2026-06-10T12:00:00Z")
            task_id = list_tasks(paths)[0]["task_id"]

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--home", tmp, "tasks", "list"])
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload)

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(
                    [
                        "--home",
                        tmp,
                        "tasks",
                        "review",
                        "--task-id",
                        task_id,
                        "--status",
                        "done",
                        "--note",
                        "Handled.",
                    ]
                )
            self.assertEqual(code, 0)
            reviewed = json.loads(output.getvalue())
            self.assertEqual(reviewed["status"], "done")
            self.assertEqual(reviewed["task"]["status"], "done")


if __name__ == "__main__":
    unittest.main()
