from __future__ import annotations

import io
import json
import tempfile
import unittest
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
    "safety",
    "next_actions",
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

    def test_invalid_task_kind_filter_is_rejected(self) -> None:
        status, payload = self.json_request("GET", "/api/tasks?kind=bogus")
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
        self.assertFalse(summary["safety"]["external_writes_performed"])
        self.assertFalse(summary["safety"]["local_audit_written"])
        self.assertEqual(before, after)

    def test_daily_run_api_records_local_audit(self) -> None:
        status, summary = self.json_request("POST", "/api/daily/run")

        self.assertEqual(status, 200)
        self.assertEqual(set(summary), DAILY_SUMMARY_FIELDS)
        self.assertGreaterEqual(summary["tasks"]["queue_count"], 1)
        self.assertGreaterEqual(summary["calendar"]["pending_count"], 1)
        self.assertFalse(summary["safety"]["external_writes_performed"])
        self.assertTrue(summary["safety"]["local_audit_written"])
        audit = next(event for event in db.list_audit_events(self.paths, limit=10) if event["action"] == "daily.run")
        self.assertEqual(audit["action"], "daily.run")
        self.assertEqual(audit["actor"], "dashboard")
        self.assertEqual(audit["metadata"]["sync_mode"], "stored_only")


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
            "/api/daily/summary",
            "/api/daily/run",
            "/api/tasks/evidence?task_id=",
            "/api/tasks/review?task_id=",
            "/api/calendar/sync?destination=ics&confirm=1",
            "/api/ask",
            'id="dailySummary"',
            'id="taskReviewQueue"',
            'id="taskQueueFilters"',
            'id="taskNavState"',
            'data-act="daily-run"',
            'data-act="show-task"',
            'data-act="task-filter-kind"',
            'data-act="task-filter-status"',
            'data-act="task-prev"',
            'data-act="task-next"',
            'data-act="task-evidence"',
            'data-act="task-done"',
            'data-act="task-needs-verification"',
            'data-act="task-reviewed"',
            'data-act="task-ignored"',
            "approval_state",
            "confirmation_id",
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
        self.assertIn("function handleTaskFilter", html)
        self.assertIn("function moveTaskCursor", html)
        self.assertIn("function taskEvidenceEmbed", html)
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
        for key in ("sync", "email", "tasks", "calendar", "safety"):
            self.assertEqual(set(sample[key]), set(live[key]))

    def test_samples_stay_synthetic(self) -> None:
        for name in ("sample_emails.json", "calendar_events.sample.json", "tasks.sample.json", "daily_summary.sample.json"):
            text = (FIXTURES_UI / name).read_text(encoding="utf-8")
            for marker in ("@gmail.", "@outlook.", "@qq.", "@163."):
                self.assertNotIn(marker, text, f"{name} must stay synthetic")


if __name__ == "__main__":
    unittest.main()
