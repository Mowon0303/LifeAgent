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
from sentineldesk.tasks import bulk_review_tasks, list_review_history, list_tasks, review_task, undo_task_review


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

    def test_list_tasks_groups_same_message_facts_by_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            message = EmailMessage(
                message_id="m-grouped",
                thread_id="t-grouped",
                sender="billing@example.com",
                subject="Two balances due",
                received_at="2026-06-10T09:00:00Z",
                body_text="Please pay $25.00 today. A separate service fee of $30.00 is also due.",
            )
            ingest_messages(paths, [message], ingested_at="2026-06-10T12:00:00Z")

            tasks = list_tasks(paths)
            amount_tasks = [task for task in tasks if task["kind"] == "amount"]

            self.assertEqual(len(amount_tasks), 1)
            self.assertEqual(amount_tasks[0]["fact_count"], 2)
            self.assertEqual(set(amount_tasks[0]["values"]), {"$25.00", "$30.00"})
            self.assertIn("2 amount facts", amount_tasks[0]["title"])

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
            self.assertEqual(audit["metadata"]["previous_status"], "new")
            self.assertTrue(audit["metadata"]["undoable"])

    def test_review_history_and_undo_restore_unreviewed_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            ingest_messages(paths, [task_message()], ingested_at="2026-06-10T12:00:00Z")
            task_id = list_tasks(paths, kind="amount")[0]["task_id"]
            review_task(
                paths,
                task_id=task_id,
                status="done",
                note="Handled.",
                actor="tester",
                updated_at="2026-06-10T12:05:00Z",
            )
            audit_id = db.list_audit_events(paths)[0]["id"]

            history = list_review_history(paths, limit=5)
            self.assertEqual(history[0]["audit_id"], audit_id)
            self.assertTrue(history[0]["undoable"])
            self.assertEqual(history[0]["previous_status"], "new")

            blocked = undo_task_review(
                paths,
                audit_id=audit_id,
                actor="tester",
                confirmed=False,
                updated_at="2026-06-10T12:06:00Z",
            )
            self.assertFalse(blocked.allowed)
            self.assertEqual(blocked.reason, "confirmation_required")
            self.assertEqual(list_tasks(paths, kind="amount", status="done")[0]["task_id"], task_id)

            restored = undo_task_review(
                paths,
                audit_id=audit_id,
                actor="tester",
                confirmed=True,
                confirmation_id="undo-single-1",
                updated_at="2026-06-10T12:07:00Z",
            )
            self.assertTrue(restored.allowed)
            self.assertEqual(restored.restored_count, 1)
            task = next(task for task in list_tasks(paths, kind="amount") if task["task_id"] == task_id)
            self.assertEqual(task["status"], "new")
            self.assertEqual(task["review_note"], "")
            self.assertEqual(task["review_actor"], "")
            history = [item for item in list_review_history(paths, limit=5) if item["audit_id"] == audit_id]
            self.assertEqual(history[0]["undo_status"], "undone")
            self.assertFalse(history[0]["undoable"])

            replay = undo_task_review(
                paths,
                audit_id=audit_id,
                actor="tester",
                confirmed=True,
                confirmation_id="undo-single-2",
                updated_at="2026-06-10T12:08:00Z",
            )
            self.assertFalse(replay.allowed)
            self.assertEqual(replay.reason, "source_audit_already_undone")

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

    def test_bulk_review_requires_confirmation_and_blocks_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            ingest_messages(paths, [task_message()], ingested_at="2026-06-10T12:00:00Z")

            blocked = bulk_review_tasks(
                paths,
                kind="amount",
                status_filter="active",
                status="done",
                actor="tester",
                confirmed=False,
                updated_at="2026-06-10T12:10:00Z",
            )

            self.assertFalse(blocked.allowed)
            self.assertEqual(blocked.reason, "confirmation_required")
            self.assertEqual(blocked.reviewed_count, 0)
            self.assertTrue([task for task in list_tasks(paths, kind="amount") if task["status"] == "new"])

            confirmed = bulk_review_tasks(
                paths,
                kind="amount",
                status_filter="active",
                status="done",
                actor="tester",
                confirmed=True,
                confirmation_id="bulk-test-1",
                updated_at="2026-06-10T12:15:00Z",
            )

            self.assertTrue(confirmed.allowed)
            self.assertEqual(confirmed.reason, "confirmed")
            self.assertEqual(confirmed.reviewed_count, 1)
            self.assertEqual(list_tasks(paths, kind="amount", status="done")[0]["status"], "done")

            replay = bulk_review_tasks(
                paths,
                kind="amount",
                status_filter="all",
                status="ignored",
                actor="tester",
                confirmed=True,
                confirmation_id="bulk-test-1",
                updated_at="2026-06-10T12:20:00Z",
            )

            self.assertFalse(replay.allowed)
            self.assertEqual(replay.reason, "confirmation_id_already_consumed")
            self.assertEqual(list_tasks(paths, kind="amount", status="done")[0]["status"], "done")
            audit_actions = [event["action"] for event in db.list_audit_events(paths, limit=10)]
            self.assertIn("task.review.bulk", audit_actions)
            self.assertIn("task.review.bulk.blocked", audit_actions)

    def test_bulk_review_history_and_undo_restore_mixed_previous_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            ingest_messages(paths, [task_message()], ingested_at="2026-06-10T12:00:00Z")
            task_ids = [task["task_id"] for task in list_tasks(paths) if task["kind"] in {"amount", "action"}]
            self.assertGreaterEqual(len(task_ids), 2)
            review_task(
                paths,
                task_id=task_ids[0],
                status="needs_verification",
                note="Check first.",
                actor="tester",
                updated_at="2026-06-10T12:09:00Z",
            )

            confirmed = bulk_review_tasks(
                paths,
                task_ids=task_ids[:2],
                status="done",
                actor="tester",
                confirmed=True,
                confirmation_id="bulk-undo-1",
                updated_at="2026-06-10T12:10:00Z",
            )
            self.assertTrue(confirmed.allowed)
            self.assertEqual(confirmed.reviewed_count, 2)
            bulk_event = next(event for event in db.list_audit_events(paths, limit=10) if event["action"] == "task.review.bulk")
            self.assertEqual(len(bulk_event["metadata"]["undo_items"]), 2)

            restored = undo_task_review(
                paths,
                audit_id=bulk_event["id"],
                actor="tester",
                confirmed=True,
                confirmation_id="bulk-undo-restore-1",
                updated_at="2026-06-10T12:11:00Z",
            )

            self.assertTrue(restored.allowed)
            self.assertEqual(restored.restored_count, 2)
            tasks = {task["task_id"]: task for task in list_tasks(paths)}
            self.assertEqual(tasks[task_ids[0]]["status"], "needs_verification")
            self.assertEqual(tasks[task_ids[0]]["review_note"], "Check first.")
            self.assertEqual(tasks[task_ids[1]]["status"], "new")
            undo_audit = db.list_audit_events(paths, limit=5)[0]
            self.assertEqual(undo_audit["action"], "task.review.undo")
            self.assertEqual(undo_audit["metadata"]["source_audit_id"], bulk_event["id"])

    def test_cli_tasks_bulk_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            ingest_messages(paths, [task_message()], ingested_at="2026-06-10T12:00:00Z")

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(
                    [
                        "--home",
                        tmp,
                        "tasks",
                        "bulk-review",
                        "--kind",
                        "action",
                        "--filter-status",
                        "active",
                        "--status",
                        "reviewed",
                        "--confirm",
                        "--confirmation-id",
                        "cli-bulk-1",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["allowed"])
            self.assertEqual(payload["reviewed_count"], 1)
            self.assertEqual(list_tasks(paths, kind="action", status="reviewed")[0]["status"], "reviewed")

    def test_cli_tasks_history_and_undo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            ingest_messages(paths, [task_message()], ingested_at="2026-06-10T12:00:00Z")
            task_id = list_tasks(paths, kind="action")[0]["task_id"]
            review_task(paths, task_id=task_id, status="done", actor="tester")
            audit_id = db.list_audit_events(paths)[0]["id"]

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--home", tmp, "tasks", "history", "--limit", "3"])
            self.assertEqual(code, 0)
            history = json.loads(output.getvalue())
            self.assertEqual(history[0]["audit_id"], audit_id)
            self.assertTrue(history[0]["undoable"])

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(
                    [
                        "--home",
                        tmp,
                        "tasks",
                        "undo",
                        "--audit-id",
                        str(audit_id),
                        "--confirm",
                        "--confirmation-id",
                        "cli-undo-1",
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["allowed"])
            self.assertEqual(list_tasks(paths, kind="action", status="new")[0]["task_id"], task_id)


if __name__ == "__main__":
    unittest.main()
