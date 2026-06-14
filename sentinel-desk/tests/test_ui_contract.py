from __future__ import annotations

import io
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from sentineldesk import db
from sentineldesk.agent.model import load_model_provider
from sentineldesk.agent.tools import default_tool_registry
from sentineldesk.agent.workflow import answer_with_workflow
from sentineldesk.config import ensure_config, ensure_dirs, get_paths, project_root
from sentineldesk.email.ingest import ingest_messages, load_email_json
from sentineldesk.server import Handler

SAMPLE_EMAILS = project_root() / "fixtures" / "ui" / "sample_emails.json"
FIXTURES_UI = project_root() / "fixtures" / "ui"

CALENDAR_ITEM_FIELDS = {
    "event_id",
    "title",
    "date_text",
    "date_key",
    "severity",
    "confidence",
    "status",
    "sync_state",
    "approval_state",
    "uncertain",
    "source_ids",
    "source_trust",
    "source_count",
    "evidence_uri",
    "reminders",
    "start_time",
    "end_time",
}
TASK_FIELDS = {
    "task_id",
    "kind",
    "title",
    "value",
    "values",
    "fact_count",
    "due_date",
    "severity",
    "confidence",
    "source_type",
    "source_refs",
    "primary_source",
    "evidence",
    "calendar_event_id",
    "sync_state",
    "updated_at",
    "needs_verification",
    "status",
    "review_note",
    "review_actor",
    "reviewed_at",
    "priority_score",
    "priority_band",
    "priority_reasons",
    "muted",
}
ASK_FIELDS = {
    "intent",
    "answer",
    "confidence",
    "uncertain",
    "requires_confirmation",
    "tool_calls",
    "citations",
    "metadata",
}
DAILY_SUMMARY_FIELDS = {
    "status",
    "generated_at",
    "mode",
    "sync",
    "email",
    "tasks",
    "calendar",
    "connectors",
    "gmail_readiness",
    "gmail_sync_diagnostics",
    "review_receipt",
    "safety",
    "next_actions",
}
GMAIL_READINESS_FIELDS = {
    "status",
    "generated_at",
    "mode",
    "account_id",
    "credentials_env",
    "token_env",
    "checks",
    "oauth_ready",
    "has_local_evidence",
    "has_cursor",
    "stored_message_count",
    "latest_received_at",
    "connector",
    "next_action",
    "external_network",
    "external_writes_performed",
}
GMAIL_READINESS_CHECK_FIELDS = {"name", "status", "detail", "metadata"}
GMAIL_SYNC_DIAGNOSTICS_FIELDS = {
    "status",
    "generated_at",
    "mode",
    "account_id",
    "latest_failure",
    "latest_success",
    "recent_failure_count",
    "recent_success_count",
    "next_action",
    "external_network",
    "external_writes_performed",
}
GMAIL_SYNC_FAILURE_FIELDS = {
    "audit_id",
    "created_at",
    "category",
    "error_type",
    "detail",
    "command",
    "query_present",
    "query_length",
    "since_present",
    "limit",
    "credentials_env",
    "token_env",
    "external_network_attempted",
    "external_writes_performed",
    "raw_error_included",
}
TASK_EVIDENCE_FIELDS = {
    "task_id",
    "task",
    "sources",
    "source_count",
    "external_network",
    "external_writes_performed",
}
TASK_EVIDENCE_SOURCE_FIELDS = {
    "source_id",
    "message_id",
    "thread_id",
    "sender",
    "subject",
    "received_at",
    "body_preview",
    "attachment_names",
    "attachment_count",
    "matched_facts",
    "fact_count",
}
TASK_REVIEW_HISTORY_FIELDS = {
    "audit_id",
    "action",
    "kind",
    "event_id",
    "actor",
    "subject",
    "created_at",
    "confirmation_id",
    "status",
    "previous_status",
    "reviewed_count",
    "task_ids",
    "undoable",
    "undo_status",
    "summary",
    "external_writes_performed",
}
TASK_REVIEW_RECEIPT_FIELDS = {
    "status",
    "generated_at",
    "mode",
    "history_limit",
    "review_event_count",
    "reviewed_task_count",
    "net_changed_task_count",
    "counts_by_status",
    "counts_by_action",
    "undoable_count",
    "undone_count",
    "latest_reviewed_at",
    "recent",
    "external_network",
    "external_writes_performed",
}
TASK_REVIEW_UNDO_FIELDS = {
    "allowed",
    "reason",
    "audit_id",
    "actor",
    "updated_at",
    "confirmation_id",
    "restored_count",
    "task_ids",
    "tasks",
    "external_writes_performed",
}
CITATION_FIELDS = {"source_id", "source_type", "evidence", "captured_at"}
SOURCE_TRUST_VALUES = {"email_evidence", "portal_verified", "trusted_doc_context", "local_evidence"}
APPROVAL_STATES = {"draft", "approved"}
TASK_STATUSES = {"new", "reviewed", "ignored", "needs_verification", "done"}
TASK_KINDS = {"deadline", "amount", "action"}


class FakeSocket:
    def __init__(self, request: bytes) -> None:
        self.request = io.BytesIO(request)
        self.response = io.BytesIO()

    def makefile(self, mode: str, *args: object, **kwargs: object) -> io.BytesIO:
        if "r" in mode:
            return self.request
        return self.response

    def sendall(self, data: bytes) -> None:
        self.response.write(data)


def parse_response(raw: bytes) -> tuple[int, dict[str, str], bytes]:
    header_bytes, body = raw.split(b"\r\n\r\n", 1)
    header_lines = header_bytes.decode("iso-8859-1").split("\r\n")
    status = int(header_lines[0].split(" ")[1])
    headers: dict[str, str] = {}
    for line in header_lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.lower()] = value.strip()
    return status, headers, body


class UiContractBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = get_paths(self.tmp.name)
        ensure_dirs(self.paths)
        ensure_config(self.paths)
        db.init_db(self.paths)
        self.messages = load_email_json(SAMPLE_EMAILS)
        ingest_messages(self.paths, self.messages, ingested_at="2026-06-25T10:00:00+00:00")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def request(self, method: str, path: str, body: str = "") -> tuple[int, dict[str, str], bytes]:
        payload = body.encode("utf-8")
        raw = (
            f"{method} {path} HTTP/1.1\r\n"
            "Host: ui-contract\r\n"
            f"Content-Length: {len(payload)}\r\n"
            "\r\n"
        ).encode("ascii") + payload
        socket = FakeSocket(raw)
        handler_class = type("UiContractHandler", (Handler,), {"paths": self.paths})
        handler_class(socket, ("127.0.0.1", 0), object())
        return parse_response(socket.response.getvalue())

    def json_request(self, method: str, path: str, body: str = "") -> tuple[int, object]:
        status, _, raw = self.request(method, path, body)
        return status, json.loads(raw.decode("utf-8"))


class CalendarEventsContractTests(UiContractBase):
    def test_calendar_events_shape(self) -> None:
        status, events = self.json_request("GET", "/api/calendar/events")
        self.assertEqual(status, 200)
        self.assertIsInstance(events, list)
        self.assertGreaterEqual(len(events), 3)
        for item in events:
            self.assertEqual(set(item), CALENDAR_ITEM_FIELDS)
            self.assertIsInstance(item["event_id"], str)
            self.assertTrue(item["event_id"])
            self.assertIsInstance(item["uncertain"], bool)
            self.assertIsInstance(item["confidence"], float)
            self.assertIsInstance(item["source_ids"], list)
            self.assertIn(item["approval_state"], APPROVAL_STATES)
            self.assertIn(item["source_trust"], SOURCE_TRUST_VALUES)
            if item["date_key"]:
                self.assertRegex(item["date_key"], r"^\d{4}-\d{2}-\d{2}$")

    def test_fresh_drafts_are_pending_and_email_sourced(self) -> None:
        status, events = self.json_request("GET", "/api/calendar/events")
        self.assertEqual(status, 200)
        for item in events:
            self.assertEqual(item["approval_state"], "draft")
            self.assertEqual(item["source_trust"], "email_evidence")

    def test_calendar_evidence_expands_source_email(self) -> None:
        status, events = self.json_request("GET", "/api/calendar/events")
        self.assertEqual(status, 200)
        event_id = events[0]["event_id"]

        status, payload = self.json_request("GET", f"/api/calendar/evidence?event_id={event_id}")
        self.assertEqual(status, 200)
        self.assertEqual(payload["event_id"], event_id)
        self.assertFalse(payload["external_network"])
        self.assertFalse(payload["external_writes_performed"])
        self.assertGreaterEqual(payload["source_count"], 1)
        source = payload["sources"][0]
        self.assertIn("subject", source)
        self.assertIn("sender", source)
        self.assertIn("body_preview", source)
        self.assertIsInstance(source["matched_facts"], list)

    def test_calendar_evidence_requires_event_id(self) -> None:
        status, payload = self.json_request("GET", "/api/calendar/evidence")
        self.assertEqual(status, 400)
        self.assertIn("event_id", payload["error"])


class TaskContractTests(UiContractBase):
    def test_tasks_shape(self) -> None:
        status, tasks = self.json_request("GET", "/api/tasks")
        self.assertEqual(status, 200)
        self.assertIsInstance(tasks, list)
        self.assertGreaterEqual(len(tasks), 4)
        for task in tasks:
            self.assertLessEqual(TASK_FIELDS, set(task))
            self.assertIn(task["status"], TASK_STATUSES)
            self.assertIn(task["kind"], TASK_KINDS)
            self.assertIsInstance(task["source_refs"], list)

    def test_calendar_tasks_reference_real_calendar_events(self) -> None:
        _, events = self.json_request("GET", "/api/calendar/events")
        event_ids = {item["event_id"] for item in events}
        _, tasks = self.json_request("GET", "/api/tasks")
        calendar_tasks = [task for task in tasks if str(task["task_id"]).startswith("calendar:")]
        self.assertTrue(calendar_tasks)
        for task in calendar_tasks:
            self.assertIn(str(task["task_id"]).split(":", 1)[1], event_ids)

    def test_tasks_filter_by_kind_status_and_limit(self) -> None:
        status, amount_tasks = self.json_request("GET", "/api/tasks?kind=amount&status=new&limit=1")
        self.assertEqual(status, 200)
        self.assertEqual(len(amount_tasks), 1)
        self.assertEqual(amount_tasks[0]["kind"], "amount")
        self.assertEqual(amount_tasks[0]["status"], "new")
        self.assertIsInstance(amount_tasks[0]["priority_score"], int)
        self.assertIn(amount_tasks[0]["priority_band"], {"high", "medium", "low", "closed"})
        self.assertIsInstance(amount_tasks[0]["priority_reasons"], list)

    def test_tasks_sort_modes_are_stable(self) -> None:
        status, priority_tasks = self.json_request("GET", "/api/tasks?sort=priority")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(priority_tasks), 2)
        scores = [task["priority_score"] for task in priority_tasks]
        self.assertEqual(scores, sorted(scores, reverse=True))

        status, due_tasks = self.json_request("GET", "/api/tasks?sort=due_date&kind=deadline")
        self.assertEqual(status, 200)
        due_dates = [task["due_date"] for task in due_tasks if task["due_date"]]
        self.assertEqual(due_dates, sorted(due_dates))

    def test_task_view_presets_filter_review_slices(self) -> None:
        status, payment_tasks = self.json_request("GET", "/api/tasks?view=payments")
        self.assertEqual(status, 200)
        self.assertTrue(payment_tasks)
        self.assertTrue(all(task["kind"] == "amount" or "payment_context" in task["priority_reasons"] for task in payment_tasks))

        status, deadline_tasks = self.json_request("GET", "/api/tasks?view=deadlines_soon")
        self.assertEqual(status, 200)
        self.assertTrue(deadline_tasks)
        self.assertTrue(all(task["kind"] == "deadline" and task["due_date"] for task in deadline_tasks))

        status, recent_tasks = self.json_request("GET", "/api/tasks?view=recently_changed")
        self.assertEqual(status, 200)
        self.assertTrue(recent_tasks)

    def test_invalid_task_kind_filter_is_rejected(self) -> None:
        status, payload = self.json_request("GET", "/api/tasks?kind=bogus")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_invalid_task_sort_is_rejected(self) -> None:
        status, payload = self.json_request("GET", "/api/tasks?sort=bogus")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_invalid_task_view_is_rejected(self) -> None:
        status, payload = self.json_request("GET", "/api/tasks?view=bogus")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_ignore_review_flow(self) -> None:
        _, tasks = self.json_request("GET", "/api/tasks")
        calendar_task = next(task for task in tasks if str(task["task_id"]).startswith("calendar:"))
        task_id = calendar_task["task_id"]
        status, receipt = self.json_request(
            "POST", f"/api/tasks/review?task_id={task_id}&status=ignored&note=ui-dismissed"
        )
        self.assertEqual(status, 200)
        self.assertEqual(receipt["status"], "ignored")
        self.assertEqual(receipt["task_id"], task_id)
        self.assertEqual(receipt["task"]["status"], "ignored")
        status, ignored = self.json_request("GET", "/api/tasks?status=ignored")
        self.assertEqual(status, 200)
        self.assertIn(task_id, {task["task_id"] for task in ignored})

    def test_email_task_done_review_flow_records_local_audit(self) -> None:
        _, tasks = self.json_request("GET", "/api/tasks")
        email_task = next(task for task in tasks if str(task["task_id"]).startswith("email:"))
        task_id = email_task["task_id"]
        before = db.list_audit_events(self.paths, limit=20)
        status, receipt = self.json_request(
            "POST", f"/api/tasks/review?task_id={task_id}&status=done&note=ui-done"
        )
        after = db.list_audit_events(self.paths, limit=20)

        self.assertEqual(status, 200)
        self.assertEqual(receipt["status"], "done")
        self.assertEqual(receipt["task_id"], task_id)
        self.assertEqual(receipt["task"]["status"], "done")
        review_events = [event for event in after if event["action"] == "task.review"]
        self.assertGreater(len(review_events), len([event for event in before if event["action"] == "task.review"]))
        self.assertEqual(review_events[0]["subject"], task_id)

    def test_bulk_review_flow_requires_confirmation_and_records_local_audit(self) -> None:
        _, amount_tasks = self.json_request("GET", "/api/tasks?kind=amount&status=new")
        task_ids = [task["task_id"] for task in amount_tasks]
        self.assertGreaterEqual(len(task_ids), 1)

        blocked_body = json.dumps(
            {
                "task_ids": task_ids,
                "status": "done",
                "note": "ui bulk blocked",
                "filter": {"kind": "amount", "status": "new"},
            }
        )
        status, blocked = self.json_request("POST", "/api/tasks/review/bulk", blocked_body)
        self.assertEqual(status, 200)
        self.assertFalse(blocked["allowed"])
        self.assertEqual(blocked["reason"], "confirmation_required")
        _, still_new = self.json_request("GET", "/api/tasks?kind=amount&status=new")
        self.assertEqual({task["task_id"] for task in still_new}, set(task_ids))

        confirmed_body = json.dumps(
            {
                "task_ids": task_ids,
                "status": "done",
                "note": "ui bulk done",
                "confirm": True,
                "confirmation_id": "ui-bulk-contract-1",
                "filter": {"kind": "amount", "status": "new"},
            }
        )
        status, confirmed = self.json_request("POST", "/api/tasks/review/bulk", confirmed_body)
        self.assertEqual(status, 200)
        self.assertTrue(confirmed["allowed"])
        self.assertEqual(confirmed["reviewed_count"], len(task_ids))
        _, done = self.json_request("GET", "/api/tasks?kind=amount&status=done")
        self.assertLessEqual(set(task_ids), {task["task_id"] for task in done})
        audit_actions = [event["action"] for event in db.list_audit_events(self.paths, limit=20)]
        self.assertIn("task.review.bulk", audit_actions)
        self.assertIn("task.review", audit_actions)
        approvals = db.list_approval_records(self.paths, limit=10)
        self.assertEqual(approvals[0]["confirmation_id"], "ui-bulk-contract-1")
        self.assertEqual(approvals[0]["action"], "task.review.bulk")

        status, replay = self.json_request("POST", "/api/tasks/review/bulk", confirmed_body)
        self.assertEqual(status, 200)
        self.assertFalse(replay["allowed"])
        self.assertEqual(replay["reason"], "confirmation_id_already_consumed")

    def test_task_review_history_is_local_readonly(self) -> None:
        _, tasks = self.json_request("GET", "/api/tasks")
        email_task = next(task for task in tasks if str(task["task_id"]).startswith("email:"))
        status, receipt = self.json_request(
            "POST", f"/api/tasks/review?task_id={email_task['task_id']}&status=done&note=history"
        )
        self.assertEqual(status, 200)
        before = db.list_audit_events(self.paths, limit=20)
        status, payload = self.json_request("GET", "/api/tasks/review/history?limit=5")
        after = db.list_audit_events(self.paths, limit=20)

        self.assertEqual(status, 200)
        self.assertEqual(set(payload), {"history", "external_network", "external_writes_performed"})
        self.assertFalse(payload["external_network"])
        self.assertFalse(payload["external_writes_performed"])
        self.assertEqual(before, after)
        self.assertGreaterEqual(len(payload["history"]), 1)
        item = payload["history"][0]
        self.assertEqual(set(item), TASK_REVIEW_HISTORY_FIELDS)
        self.assertEqual(item["action"], "task.review")
        self.assertEqual(item["task_ids"], [receipt["task_id"]])
        self.assertTrue(item["undoable"])

    def test_task_review_receipt_summary_is_local_readonly(self) -> None:
        _, tasks = self.json_request("GET", "/api/tasks")
        email_task = next(task for task in tasks if str(task["task_id"]).startswith("email:"))
        status, receipt = self.json_request(
            "POST", f"/api/tasks/review?task_id={email_task['task_id']}&status=done&note=receipt"
        )
        self.assertEqual(status, 200)
        before = db.list_audit_events(self.paths, limit=20)
        status, payload = self.json_request("GET", "/api/tasks/review/summary?limit=10&recent_limit=3")
        after = db.list_audit_events(self.paths, limit=20)

        self.assertEqual(status, 200)
        self.assertEqual(set(payload), TASK_REVIEW_RECEIPT_FIELDS)
        self.assertEqual(before, after)
        self.assertEqual(payload["mode"], "local_review_receipt")
        self.assertEqual(payload["history_limit"], 10)
        self.assertEqual(payload["review_event_count"], 1)
        self.assertEqual(payload["reviewed_task_count"], 1)
        self.assertEqual(payload["net_changed_task_count"], 1)
        self.assertEqual(payload["counts_by_status"]["done"], 1)
        self.assertFalse(payload["external_network"])
        self.assertFalse(payload["external_writes_performed"])
        self.assertEqual(payload["recent"][0]["task_ids"], [receipt["task_id"]])

    def test_task_review_undo_requires_confirmation_and_restores_locally(self) -> None:
        _, tasks = self.json_request("GET", "/api/tasks")
        email_task = next(task for task in tasks if str(task["task_id"]).startswith("email:"))
        task_id = email_task["task_id"]
        status, _ = self.json_request("POST", f"/api/tasks/review?task_id={task_id}&status=done")
        self.assertEqual(status, 200)
        audit_id = next(event["id"] for event in db.list_audit_events(self.paths, limit=20) if event["action"] == "task.review")

        status, blocked = self.json_request("POST", "/api/tasks/review/undo", json.dumps({"audit_id": audit_id}))
        self.assertEqual(status, 200)
        self.assertEqual(set(blocked), TASK_REVIEW_UNDO_FIELDS)
        self.assertFalse(blocked["allowed"])
        self.assertEqual(blocked["reason"], "confirmation_required")
        _, done = self.json_request("GET", "/api/tasks?status=done")
        self.assertIn(task_id, {task["task_id"] for task in done})

        body = json.dumps({"audit_id": audit_id, "confirm": True, "confirmation_id": "ui-undo-contract-1"})
        status, restored = self.json_request("POST", "/api/tasks/review/undo", body)
        self.assertEqual(status, 200)
        self.assertTrue(restored["allowed"])
        self.assertEqual(restored["restored_count"], 1)
        self.assertFalse(restored["external_writes_performed"])
        _, new_tasks = self.json_request("GET", "/api/tasks?status=new")
        self.assertIn(task_id, {task["task_id"] for task in new_tasks})
        approvals = db.list_approval_records(self.paths, limit=5)
        self.assertEqual(approvals[0]["action"], "task.review.undo")
        self.assertEqual(approvals[0]["confirmation_id"], "ui-undo-contract-1")

    def test_task_evidence_drilldown_is_local_readonly(self) -> None:
        _, tasks = self.json_request("GET", "/api/tasks")
        email_task = next(task for task in tasks if str(task["task_id"]).startswith("email:"))
        before = db.list_audit_events(self.paths, limit=20)
        status, payload = self.json_request("GET", f"/api/tasks/evidence?task_id={email_task['task_id']}")
        after = db.list_audit_events(self.paths, limit=20)

        self.assertEqual(status, 200)
        self.assertEqual(set(payload), TASK_EVIDENCE_FIELDS)
        self.assertEqual(payload["task_id"], email_task["task_id"])
        self.assertFalse(payload["external_network"])
        self.assertFalse(payload["external_writes_performed"])
        self.assertEqual(before, after)
        self.assertGreaterEqual(payload["source_count"], 1)
        source = payload["sources"][0]
        self.assertEqual(set(source), TASK_EVIDENCE_SOURCE_FIELDS)
        self.assertTrue(source["message_id"])
        self.assertTrue(source["subject"])
        self.assertTrue(source["body_preview"])
        self.assertGreaterEqual(source["fact_count"], 1)
        self.assertTrue(any(fact["kind"] == email_task["kind"] for fact in source["matched_facts"]))

    def test_invalid_review_status_is_rejected(self) -> None:
        status, payload = self.json_request("POST", "/api/tasks/review?task_id=calendar:x&status=bogus")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_missing_task_evidence_is_rejected(self) -> None:
        status, payload = self.json_request("GET", "/api/tasks/evidence?task_id=email:missing")
        self.assertEqual(status, 404)
        self.assertIn("error", payload)


class DailyContractTests(UiContractBase):
    def test_daily_summary_is_readonly_snapshot(self) -> None:
        before = [event for event in db.list_audit_events(self.paths, limit=20) if event["action"] == "daily.run"]
        status, summary = self.json_request("GET", "/api/daily/summary")
        after = [event for event in db.list_audit_events(self.paths, limit=20) if event["action"] == "daily.run"]

        self.assertEqual(status, 200)
        self.assertEqual(set(summary), DAILY_SUMMARY_FIELDS)
        self.assertEqual(summary["mode"], "daily_landing")
        self.assertEqual(summary["sync"]["mode"], "stored_only")
        self.assertFalse(summary["sync"]["external_network"])
        self.assertEqual(set(summary["gmail_readiness"]), GMAIL_READINESS_FIELDS)
        self.assertTrue(summary["gmail_readiness"]["has_local_evidence"])
        self.assertFalse(summary["gmail_readiness"]["external_network"])
        self.assertFalse(summary["gmail_readiness"]["external_writes_performed"])
        self.assertTrue(all(set(check) == GMAIL_READINESS_CHECK_FIELDS for check in summary["gmail_readiness"]["checks"]))
        self.assertEqual(set(summary["gmail_sync_diagnostics"]), GMAIL_SYNC_DIAGNOSTICS_FIELDS)
        self.assertEqual(summary["gmail_sync_diagnostics"]["status"], "no_attempt")
        self.assertFalse(summary["gmail_sync_diagnostics"]["external_network"])
        self.assertFalse(summary["gmail_sync_diagnostics"]["external_writes_performed"])
        self.assertEqual(summary["review_receipt"]["mode"], "local_review_receipt")
        self.assertFalse(summary["safety"]["external_writes_performed"])
        self.assertFalse(summary["safety"]["local_audit_written"])
        self.assertEqual(before, after)

    def test_gmail_readiness_api_is_local_readonly_and_redacted(self) -> None:
        db.upsert_connector_state(
            self.paths,
            connector="gmail_api",
            account_id="student.private@example.com",
            cursor="history-secret-123",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            metadata={"source_type": "gmail_api", "trust_label": "gmail_readonly"},
            updated_at="2026-06-12T00:00:00+00:00",
        )
        before = db.list_audit_events(self.paths, limit=20)
        status, payload = self.json_request("GET", "/api/gmail/readiness?account=student.private@example.com")
        after = db.list_audit_events(self.paths, limit=20)

        raw = json.dumps(payload)
        self.assertEqual(status, 200)
        self.assertEqual(set(payload), GMAIL_READINESS_FIELDS)
        self.assertEqual(payload["mode"], "gmail_first_readiness")
        self.assertTrue(payload["has_cursor"])
        self.assertTrue(payload["has_local_evidence"])
        self.assertFalse(payload["external_network"])
        self.assertFalse(payload["external_writes_performed"])
        self.assertNotIn("student.private@example.com", raw)
        self.assertNotIn("history-secret-123", raw)
        self.assertEqual(before, after)

    def test_gmail_sync_diagnostics_api_is_local_readonly_and_redacted(self) -> None:
        db.insert_audit_event(
            self.paths,
            action="email.connector.sync.failed",
            actor="test",
            subject="gmail_api:[REDACTED_CONNECTOR_METADATA]",
            capability="email_read",
            side_effect="external_read_failed_local_audit",
            allowed=False,
            confirmation_id="",
            metadata={
                "connector": "gmail_api",
                "account_id": "[REDACTED_CONNECTOR_METADATA]",
                "command": "daily run --sync-gmail",
                "category": "permission_denied",
                "error_type": "HttpError",
                "detail": "Google denied Gmail API access; check the app test user and Gmail readonly scope.",
                "query_present": True,
                "query_length": 8,
                "since_present": True,
                "limit": 50,
                "credentials_env": "SENTINEL_GOOGLE_CREDENTIALS_JSON",
                "token_env": "SENTINEL_GOOGLE_TOKEN_JSON",
                "external_network_attempted": True,
                "external_writes_performed": False,
                "raw_error_included": False,
            },
            created_at="2026-06-12T12:00:00+00:00",
        )
        before = db.list_audit_events(self.paths, limit=20)
        status, payload = self.json_request("GET", "/api/gmail/sync-diagnostics?account=student.private@example.com")
        after = db.list_audit_events(self.paths, limit=20)

        raw = json.dumps(payload)
        self.assertEqual(status, 200)
        self.assertEqual(set(payload), GMAIL_SYNC_DIAGNOSTICS_FIELDS)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(set(payload["latest_failure"]), GMAIL_SYNC_FAILURE_FIELDS)
        self.assertEqual(payload["latest_failure"]["category"], "permission_denied")
        self.assertEqual(payload["next_action"]["kind"], "refresh_gmail_oauth")
        self.assertFalse(payload["external_network"])
        self.assertFalse(payload["external_writes_performed"])
        self.assertNotIn("student.private@example.com", raw)
        self.assertEqual(before, after)

    def test_daily_run_api_records_local_audit(self) -> None:
        status, summary = self.json_request("POST", "/api/daily/run")

        self.assertEqual(status, 200)
        self.assertEqual(set(summary), DAILY_SUMMARY_FIELDS)
        self.assertGreaterEqual(summary["tasks"]["queue_count"], 1)
        self.assertGreaterEqual(summary["calendar"]["pending_count"], 1)
        self.assertEqual(summary["review_receipt"]["status"], "ready")
        self.assertFalse(summary["safety"]["external_writes_performed"])
        self.assertTrue(summary["safety"]["local_audit_written"])
        audit = next(event for event in db.list_audit_events(self.paths, limit=10) if event["action"] == "daily.run")
        self.assertEqual(audit["action"], "daily.run")
        self.assertEqual(audit["actor"], "dashboard")
        self.assertEqual(audit["metadata"]["sync_mode"], "stored_only")

    def test_gmail_sync_api_requires_explicit_confirmation(self) -> None:
        before = db.list_audit_events(self.paths, limit=20)
        status, payload = self.json_request("POST", "/api/gmail/sync")
        after = db.list_audit_events(self.paths, limit=20)

        self.assertEqual(status, 200)
        self.assertFalse(payload["allowed"])
        self.assertTrue(payload["requires_confirmation"])
        self.assertEqual(payload["action"], "gmail.readonly_sync")
        self.assertEqual(payload["side_effect"], "gmail_readonly_plus_local_db_write")
        self.assertFalse(payload["external_network"])
        self.assertFalse(payload["external_writes_performed"])
        self.assertEqual(before, after)

    def test_gmail_sync_api_failure_updates_redacted_diagnostics(self) -> None:
        with mock.patch(
            "sentineldesk.server.handlers_daily_gmail.run_gmail_readonly_sync",
            side_effect=RuntimeError("403 insufficientPermissions token-secret student.private@example.com"),
        ):
            status, payload = self.json_request(
                "POST", "/api/gmail/sync?confirm=1&account=student.private@example.com&query=deadline"
            )

        raw = json.dumps(payload)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "failed")
        self.assertTrue(payload["allowed"])
        self.assertEqual(payload["error"], "gmail_sync_failed")
        self.assertTrue(payload["external_network"])
        self.assertFalse(payload["external_writes_performed"])
        self.assertEqual(payload["diagnostics"]["latest_failure"]["category"], "permission_denied")
        self.assertEqual(payload["diagnostics"]["latest_failure"]["command"], "api gmail sync")
        self.assertEqual(payload["daily_summary"]["gmail_sync_diagnostics"]["status"], "failed")
        self.assertNotIn("student.private@example.com", raw)
        self.assertNotIn("token-secret", raw)
        audit = next(event for event in db.list_audit_events(self.paths, limit=10) if event["action"] == "email.connector.sync.failed")
        self.assertEqual(audit["action"], "email.connector.sync.failed")
        self.assertFalse(audit["allowed"])

    def test_gmail_sync_api_success_redacts_sync_summary(self) -> None:
        sync_summary = {
            "mode": "gmail_readonly",
            "external_network": True,
            "query": "deadline",
            "account_id": "student.private@example.com",
            "cursor": "history-secret-123",
            "cursor_saved": True,
            "messages_seen": 0,
            "messages_persisted": 0,
            "facts_extracted": 0,
            "deadline_events_drafted": 0,
        }
        with mock.patch("sentineldesk.server.handlers_daily_gmail.run_gmail_readonly_sync", return_value=sync_summary):
            status, payload = self.json_request("POST", "/api/gmail/sync?confirm=1&account=student.private@example.com")

        raw = json.dumps(payload)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ready")
        self.assertTrue(payload["allowed"])
        self.assertTrue(payload["external_network"])
        self.assertFalse(payload["external_writes_performed"])
        self.assertEqual(payload["sync"]["account_id"], "[REDACTED_CONNECTOR_METADATA]")
        self.assertEqual(payload["sync"]["cursor"], "[REDACTED_CONNECTOR_METADATA]")
        self.assertFalse(payload["daily_summary"]["safety"]["external_writes_performed"])
        self.assertNotIn("student.private@example.com", raw)
        self.assertNotIn("history-secret-123", raw)


class ConfirmFlowContractTests(UiContractBase):
    def test_confirm_turns_pending_into_approved(self) -> None:
        _, events = self.json_request("GET", "/api/calendar/events")
        target = events[0]
        self.assertEqual(target["approval_state"], "draft")
        event_id = target["event_id"]
        status, blocked = self.json_request(
            "POST", f"/api/calendar/sync?destination=ics&event_id={event_id}"
        )
        self.assertEqual(status, 200)
        self.assertFalse(blocked["allowed"])
        status, receipt = self.json_request(
            "POST",
            f"/api/calendar/sync?destination=ics&confirm=1&confirmation_id=ui-{event_id}-1&event_id={event_id}",
        )
        self.assertEqual(status, 200)
        self.assertTrue(receipt["allowed"])
        self.assertIn(event_id, receipt["event_ids"])
        _, refreshed = self.json_request("GET", "/api/calendar/events")
        updated = next(item for item in refreshed if item["event_id"] == event_id)
        self.assertEqual(updated["approval_state"], "approved")
        self.assertEqual(updated["sync_state"], "ics_exported")

    def test_confirmation_id_replay_is_blocked(self) -> None:
        _, events = self.json_request("GET", "/api/calendar/events")
        event_id = events[0]["event_id"]
        path = f"/api/calendar/sync?destination=ics&confirm=1&confirmation_id=ui-replay&event_id={event_id}"
        status, first = self.json_request("POST", path)
        self.assertEqual(status, 200)
        self.assertTrue(first["allowed"])
        status, second = self.json_request("POST", path)
        self.assertEqual(status, 200)
        self.assertFalse(second["allowed"])


class AskContractTests(UiContractBase):
    def test_ask_answer_shape(self) -> None:
        status, answer = self.json_request(
            "POST", "/api/ask", body=json.dumps({"question": "What is my latest deadline?"})
        )
        self.assertEqual(status, 200)
        self.assertEqual(set(answer), ASK_FIELDS)
        self.assertIn(answer["confidence"], {"high", "medium", "uncertain"})
        self.assertIsInstance(answer["uncertain"], bool)
        self.assertIsInstance(answer["tool_calls"], list)
        self.assertIn("search_latest_email", answer["tool_calls"])
        self.assertIsInstance(answer["citations"], list)
        self.assertIn("workflow_engine", answer["metadata"])

    def test_ask_without_question_is_rejected(self) -> None:
        status, payload = self.json_request("POST", "/api/ask", body="{}")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_ask_reads_stored_email_evidence(self) -> None:
        status, answer = self.json_request(
            "POST", "/api/ask", body=json.dumps({"question": "What is my latest deadline?"})
        )
        self.assertEqual(status, 200)
        self.assertTrue(answer["citations"], "stored email evidence should reach the answer")
        self.assertTrue(answer["uncertain"], "four stored deadlines conflict, so the answer must stay uncertain")
        cited = {citation["source_id"] for citation in answer["citations"]}
        self.assertTrue(any(source.startswith("stored_email:") for source in cited))

    def test_ask_reaches_verified_answer_with_single_stored_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as single_home:
            paths = get_paths(single_home)
            ensure_dirs(paths)
            ensure_config(paths)
            db.init_db(paths)
            ingest_messages(
                paths,
                [m for m in self.messages if m.message_id == "ui-sample-rent-001"],
                ingested_at="2026-06-25T10:00:00+00:00",
            )
            raw = (
                "POST /api/ask HTTP/1.1\r\nHost: ui-contract\r\n"
            )
            body = json.dumps({"question": "What is my latest deadline?"})
            payload = body.encode("utf-8")
            raw = raw + f"Content-Length: {len(payload)}\r\n\r\n"
            socket = FakeSocket(raw.encode("ascii") + payload)
            handler_class = type("SingleHomeHandler", (Handler,), {"paths": paths})
            handler_class(socket, ("127.0.0.1", 0), object())
            status, _, response = parse_response(socket.response.getvalue())
            answer = json.loads(response.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertFalse(answer["uncertain"])
        self.assertIn("07/01/2026", answer["answer"])
        self.assertTrue(answer["citations"])

    def test_citation_payload_shape_with_email_evidence(self) -> None:
        answer = answer_with_workflow(
            "What is my latest deadline?",
            provider=load_model_provider(self.paths),
            messages=self.messages,
            registry=default_tool_registry(self.paths),
        )
        self.assertTrue(answer.citations)
        for citation in answer.citations:
            self.assertEqual(set(citation.__dict__), CITATION_FIELDS)
            self.assertTrue(citation.source_id)
            self.assertTrue(citation.evidence)


class CalendarPageTests(UiContractBase):
    def test_root_serves_calendar_and_ops_serves_legacy_dashboard(self) -> None:
        status, _, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn('id="calApp"', body.decode("utf-8"))
        status, _, body = self.request("GET", "/ops")
        self.assertEqual(status, 200)
        self.assertIn('id="scenarioSelect"', body.decode("utf-8"))

    def test_calendar_page_links_to_ops_dashboard(self) -> None:
        _, _, body = self.request("GET", "/")
        self.assertIn('href="/ops"', body.decode("utf-8"))

    def test_calendar_page_served_with_contract_wiring(self) -> None:
        status, headers, body = self.request("GET", "/calendar")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["content-type"])
        html = body.decode("utf-8")
        for marker in (
            'id="calApp"',
            'id="calSeg"',
            'id="calBody"',
            'id="aiFeed"',
            'id="aiInput"',
            'data-view="month"',
            'data-view="week"',
            'data-view="day"',
            'data-view="agenda"',
            "/api/calendar/events",
            "/api/tasks",
            "/api/tasks?view=",
            "&sort=",
            "/api/tasks?view=all&sort=priority&limit=1000",
            "/api/daily/summary",
            "/api/daily/run",
            "/api/gmail/sync?confirm=1",
            "/api/tasks/evidence?task_id=",
            "/api/calendar/evidence?event_id=",
            "/api/tasks/review?task_id=",
            "/api/tasks/review/bulk",
            "/api/tasks/review/history",
            "/api/tasks/review/undo",
            "/api/calendar/sync?destination=ics&confirm=1",
            "/api/ask",
            'id="dailySummary"',
            'id="taskReviewQueue"',
            'id="taskQueueFilters"',
            'id="taskNavState"',
            'id="taskSessionSummary"',
            'id="taskReviewReceipt"',
            'id="gmailReadiness"',
            'id="gmailSyncDiagnostics"',
            'id="gmailSyncBoundary"',
            'id="taskBulkActions"',
            'data-act="task-view"',
            'data-act="task-group"',
            'data-task-filter="group"',
            "var TASK_VIEWS = ['all', 'needs_verification', 'payments', 'deadlines_soon', 'recently_changed'];",
            "var TASK_GROUPS = ['all', 'unread', 'read', 'ignored'];",
            'data-act="task-history"',
            'data-act="task-undo"',
            'data-act="daily-run"',
            'data-act="gmail-sync"',
            'data-act="show-task"',
            'data-act="task-prev"',
            'data-act="task-next"',
            'data-act="task-bulk-done"',
            'data-act="task-bulk-reviewed"',
            'data-act="task-bulk-ignored"',
            'data-act="calendar-evidence"',
            "function openCalendarEvidence",
            "function calendarEvidenceSourceHtml",
            "function visibleCalendarItems",
            "function pendingCalendarItems",
            "确认前不显示在日历",
            "候选截止日",
            "收到 ",
            'data-act="task-done"',
            'data-act="task-ignored"',
            'data-act="task-card"',
            "approval_state",
            "confirmation_id",
            "function reviewReceiptPanel",
            "function receiptStatusText",
            "function gmailReadinessPanel",
            "function gmailSyncDiagnosticsPanel",
        ):
            self.assertIn(marker, html)

    def test_calendar_page_refreshes_summary_after_actions(self) -> None:
        _, _, body = self.request("GET", "/")
        html = body.decode("utf-8")
        self.assertIn('id="aiSummary"', html)
        self.assertIn('id="dailySummary"', html)
        self.assertIn("function updateSummary()", html)
        self.assertIn("function dailyEmbed()", html)
        self.assertIn("function handleDailyRun", html)
        self.assertIn("function taskReviewCard", html)
        self.assertIn("function filteredTaskQueue", html)
        self.assertIn("function taskFilterControls", html)
        self.assertIn("function taskSessionPanel", html)
        self.assertIn("function taskSessionStats", html)
        self.assertIn("function gmailReadinessPanel", html)
        self.assertIn("function gmailSyncDiagnosticsPanel", html)
        self.assertIn("function taskViewStats", html)
        self.assertIn("function taskMatchesSavedView", html)
        self.assertIn("function taskSessionEmptyCopy", html)
        self.assertIn("function taskEmptyStateMessage", html)
        self.assertIn("function advancePastTask", html)
        self.assertIn("function handleTaskFilter", html)
        self.assertIn("function handleTaskView", html)
        self.assertIn("function handleTaskSort", html)
        self.assertIn("function taskApiUrl", html)
        self.assertIn("function moveTaskCursor", html)
        self.assertIn("function handleTaskBulkReview", html)
        self.assertIn("function taskEvidenceEmbed", html)
        self.assertIn("function taskHistoryEmbed", html)
        self.assertIn("function handleTaskHistory", html)
        self.assertIn("function handleTaskUndo", html)
        self.assertIn("function offerNextTaskSuggestion", html)
        self.assertIn("function handleTaskReview", html)
        self.assertIn("function handleTaskEvidence", html)
        refresh_body = html.split("function refresh()", 1)[1].split("// ---------- boot ----------", 1)[0]
        self.assertIn("updateSummary()", refresh_body, "refresh() must recompute the assistant summary and topic")

    def test_calendar_page_has_no_external_script_dependencies(self) -> None:
        _, _, body = self.request("GET", "/calendar")
        html = body.decode("utf-8")
        self.assertNotIn("<script src=", html)
        self.assertNotIn("cdn.", html)


class UiFixtureSampleTests(UiContractBase):
    def test_committed_calendar_sample_matches_live_shape(self) -> None:
        sample = json.loads((FIXTURES_UI / "calendar_events.sample.json").read_text(encoding="utf-8"))
        self.assertTrue(sample)
        _, live = self.json_request("GET", "/api/calendar/events")
        self.assertEqual({frozenset(item) for item in sample}, {frozenset(item) for item in live})
        self.assertEqual(
            sorted(item["title"] for item in sample), sorted(item["title"] for item in live)
        )

    def test_committed_tasks_sample_matches_live_shape(self) -> None:
        sample = json.loads((FIXTURES_UI / "tasks.sample.json").read_text(encoding="utf-8"))
        self.assertTrue(sample)
        _, live = self.json_request("GET", "/api/tasks")
        self.assertEqual({frozenset(item) for item in sample}, {frozenset(item) for item in live})

    def test_committed_ask_sample_matches_live_shape(self) -> None:
        sample = json.loads((FIXTURES_UI / "ask_answer.sample.json").read_text(encoding="utf-8"))
        status, live = self.json_request(
            "POST", "/api/ask", body=json.dumps({"question": "What is my latest deadline?"})
        )
        self.assertEqual(status, 200)
        self.assertEqual(set(sample), set(live))

    def test_committed_daily_sample_matches_live_shape(self) -> None:
        sample = json.loads((FIXTURES_UI / "daily_summary.sample.json").read_text(encoding="utf-8"))
        status, live = self.json_request("GET", "/api/daily/summary?task_limit=0&calendar_limit=0")
        self.assertEqual(status, 200)
        self.assertEqual(set(sample), set(live))
        for key in ("sync", "email", "tasks", "calendar", "gmail_readiness", "gmail_sync_diagnostics", "safety"):
            self.assertEqual(set(sample[key]), set(live[key]))

    def test_samples_stay_synthetic(self) -> None:
        for name in ("sample_emails.json", "calendar_events.sample.json", "tasks.sample.json", "daily_summary.sample.json"):
            text = (FIXTURES_UI / name).read_text(encoding="utf-8")
            for marker in ("@gmail.", "@outlook.", "@qq.", "@163."):
                self.assertNotIn(marker, text, f"{name} must stay synthetic")


if __name__ == "__main__":
    unittest.main()
