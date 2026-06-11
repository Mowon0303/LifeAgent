from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile

from sentineldesk import db
from sentineldesk.config import ensure_config, ensure_dirs, get_paths
from sentineldesk.email.ingest import ingest_messages
from sentineldesk.email.models import EmailMessage
from sentineldesk.scenarios import apply_scenario
from sentineldesk.server import Handler


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


class DashboardSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = get_paths(self.tmp.name)
        ensure_dirs(self.paths)
        ensure_config(self.paths)
        db.init_db(self.paths)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def request(self, method: str, path: str) -> tuple[int, dict[str, str], bytes]:
        raw = (
            f"{method} {path} HTTP/1.1\r\n"
            "Host: dashboard-smoke\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        ).encode("ascii")
        socket = FakeSocket(raw)
        handler_class = type("DashboardSmokeHandler", (Handler,), {"paths": self.paths})
        handler_class(socket, ("127.0.0.1", 0), object())
        return parse_response(socket.response.getvalue())

    def json_request(self, method: str, path: str) -> tuple[int, dict[str, str], object]:
        status, headers, body = self.request(method, path)
        return status, headers, json.loads(body.decode("utf-8"))

    def test_dashboard_html_exposes_scenario_and_evidence_controls(self) -> None:
        status, headers, body = self.request("GET", "/")
        html = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["content-type"])
        self.assertIn('id="scenarioSelect"', html)
        self.assertIn('id="applyScenarioRun"', html)
        self.assertIn('id="redactedToggle"', html)
        self.assertIn('<a id="downloadPackage"', html)
        self.assertIn('download>Download Package</a>', html)
        self.assertIn('id="calendarDrafts"', html)
        self.assertIn('id="calendarBoard"', html)
        self.assertIn('data-calendar-view="month"', html)
        self.assertIn('id="calendarPrev"', html)
        self.assertIn('class="deadline-chip', html)
        self.assertIn("/api/calendar/drafts", html)
        self.assertIn("/api/calendar/drafts/update?", html)
        self.assertIn("/api/calendar/events", html)
        self.assertIn("/api/calendar/sync?destination=ics&confirm=1&event_id=", html)
        self.assertIn("data-calendar-edit", html)
        self.assertIn("data-calendar-date", html)
        self.assertIn("data-calendar-sync", html)
        self.assertIn("approval_state", html)
        self.assertIn("source_trust", html)
        self.assertIn("/api/email/facts?kind=deadline", html)
        self.assertIn("/api/audit/events", html)
        self.assertIn("/api/approvals", html)
        self.assertIn('id="approvalCount"', html)
        self.assertIn('id="approvalHistory"', html)
        self.assertIn('class="approval"', html)
        self.assertIn("confirmation=", html)
        self.assertIn('id="retentionBefore"', html)
        self.assertIn('id="retentionPreview"', html)
        self.assertIn('id="retentionPurge"', html)
        self.assertIn("data-retention-source", html)
        self.assertIn("/api/retention/purge?", html)
        self.assertIn("Permanently purge selected local records?", html)
        self.assertNotIn("a.metadata", html)
        self.assertIn("/api/connectors/state", html)
        self.assertIn("/api/scenario?run=1", html)
        self.assertIn("/api/package/", html)

    def test_email_and_calendar_api_exposes_persisted_drafts(self) -> None:
        ingest_messages(
            self.paths,
            [
                EmailMessage(
                    message_id="m-dashboard",
                    thread_id="t-dashboard",
                    sender="leasing@example.com",
                    subject="Move-out Notice Reminder",
                    received_at="2026-06-10",
                    body_text="Please submit written notice by July 2, 2026.",
                )
            ],
            ingested_at="2026-06-10T12:00:00Z",
        )

        facts_status, _, facts = self.json_request("GET", "/api/email/facts?kind=deadline")
        drafts_status, _, drafts = self.json_request("GET", "/api/calendar/drafts")
        events_status, _, events = self.json_request("GET", "/api/calendar/events")
        audit_status, _, audit_events = self.json_request("GET", "/api/audit/events")
        self.assertEqual(facts_status, 200)
        self.assertEqual(drafts_status, 200)
        self.assertEqual(events_status, 200)
        self.assertEqual(audit_status, 200)
        self.assertEqual(facts[0]["source_id"], "email:m-dashboard")
        self.assertEqual(drafts[0]["source_ids"], ["email:m-dashboard"])
        self.assertEqual(drafts[0]["status"], "draft")
        self.assertEqual(drafts[0]["sync_state"], "local_draft")
        self.assertEqual(events[0]["date_key"], "2026-07-02")
        self.assertEqual(events[0]["approval_state"], "draft")
        self.assertEqual(events[0]["source_trust"], "email_evidence")
        self.assertEqual(events[0]["source_count"], 1)
        self.assertEqual(audit_events[0]["action"], "email.ingest")

    def test_calendar_sync_api_requires_confirmation_and_exports_ics(self) -> None:
        ingest_messages(
            self.paths,
            [
                EmailMessage(
                    message_id="m-sync",
                    thread_id="t-sync",
                    sender="leasing@example.com",
                    subject="Move-out Notice Reminder",
                    received_at="2026-06-10",
                    body_text="Please submit written notice by July 2, 2026.",
                )
            ],
            ingested_at="2026-06-10T12:00:00Z",
        )
        drafts = db.list_calendar_drafts(self.paths)
        event_id = drafts[0]["event_id"]

        blocked_status, _, blocked = self.json_request("POST", f"/api/calendar/sync?destination=ics&event_id={event_id}")
        self.assertEqual(blocked_status, 200)
        self.assertFalse(blocked["allowed"])
        self.assertFalse((self.paths.artifacts / "calendar" / "lifeagent-deadlines.ics").exists())
        self.assertEqual(db.list_approval_records(self.paths), [])

        sync_status, _, synced = self.json_request("POST", f"/api/calendar/sync?destination=ics&confirm=1&event_id={event_id}")
        self.assertEqual(sync_status, 200)
        self.assertTrue(synced["allowed"])
        output = self.paths.artifacts / "calendar" / "lifeagent-deadlines.ics"
        self.assertTrue(output.exists())
        self.assertIn("BEGIN:VCALENDAR", output.read_text(encoding="utf-8"))
        updated = db.list_calendar_drafts(self.paths)[0]
        self.assertEqual(updated["status"], "synced")
        self.assertEqual(updated["sync_state"], "ics_exported")
        approval_status, _, approvals = self.json_request("GET", "/api/approvals")
        self.assertEqual(approval_status, 200)
        self.assertEqual(approvals[0]["actor"], "dashboard")
        self.assertEqual(approvals[0]["action"], "calendar.sync")
        self.assertEqual(approvals[0]["evidence_refs"], ["email:m-sync"])
        events_status, _, events = self.json_request("GET", "/api/calendar/events")
        self.assertEqual(events_status, 200)
        self.assertEqual(events[0]["approval_state"], "approved")
        self.assertEqual(events[0]["sync_state"], "ics_exported")
        self.assertEqual(events[0]["status"], "synced")

    def test_calendar_draft_update_api_resets_synced_state_to_local_draft(self) -> None:
        ingest_messages(
            self.paths,
            [
                EmailMessage(
                    message_id="m-edit",
                    thread_id="t-edit",
                    sender="leasing@example.com",
                    subject="Move-out Notice Reminder",
                    received_at="2026-06-10",
                    body_text="Please submit written notice by July 2, 2026.",
                )
            ],
            ingested_at="2026-06-10T12:00:00Z",
        )
        event_id = db.list_calendar_drafts(self.paths)[0]["event_id"]
        db.update_calendar_draft_sync_state(
            self.paths,
            event_id=event_id,
            sync_state="ics_exported",
            status="synced",
            updated_at="2026-06-10T12:05:00Z",
        )

        status, _, payload = self.json_request(
            "POST",
            f"/api/calendar/drafts/update?event_id={event_id}&date=2026-07-03",
        )

        self.assertEqual(status, 200)
        self.assertFalse(payload["external_write"])
        self.assertEqual(payload["updated"]["date_text"], "2026-07-03")
        self.assertEqual(payload["updated"]["status"], "draft")
        self.assertEqual(payload["updated"]["sync_state"], "local_draft")
        self.assertEqual(db.list_approval_records(self.paths), [])
        events_status, _, events = self.json_request("GET", "/api/calendar/events")
        self.assertEqual(events_status, 200)
        self.assertEqual(events[0]["date_key"], "2026-07-03")
        self.assertEqual(events[0]["approval_state"], "draft")
        self.assertEqual(events[0]["sync_state"], "local_draft")
        audit = db.list_audit_events(self.paths)[0]
        self.assertEqual(audit["action"], "calendar.edit")
        self.assertEqual(audit["actor"], "dashboard")
        self.assertEqual(audit["side_effect"], "local_db_write")

    def test_retention_api_is_preview_first_and_confirmation_gated(self) -> None:
        ingest_messages(
            self.paths,
            [
                EmailMessage(
                    message_id="m-old",
                    thread_id="t-old",
                    sender="leasing@example.com",
                    subject="Old Notice",
                    received_at="2026-01-01",
                    body_text="Please submit written notice by January 15, 2026.",
                )
            ],
            ingested_at="2026-01-01T00:00:00Z",
        )

        preview_status, _, preview = self.json_request(
            "POST",
            "/api/retention/purge?before=2026-02-01&source=email&source=calendar",
        )
        self.assertEqual(preview_status, 200)
        self.assertTrue(preview["dry_run"])
        self.assertFalse(preview["deleted"])
        self.assertEqual(preview["counts"], {"email": 1, "calendar": 1})
        self.assertTrue(db.list_email_messages(self.paths))
        self.assertTrue(db.list_calendar_drafts(self.paths))

        purge_status, _, purged = self.json_request(
            "POST",
            "/api/retention/purge?before=2026-02-01&source=email&source=calendar&confirm=1",
        )
        self.assertEqual(purge_status, 200)
        self.assertFalse(purged["dry_run"])
        self.assertTrue(purged["deleted"])
        self.assertEqual(db.list_email_messages(self.paths), [])
        self.assertEqual(db.list_calendar_drafts(self.paths), [])
        self.assertEqual(db.list_audit_events(self.paths)[0]["action"], "retention.purge")

    def test_connector_state_api_exposes_incremental_cursor_metadata(self) -> None:
        db.upsert_connector_state(
            self.paths,
            connector="gmail_api",
            account_id="me@example.com",
            cursor="history-123",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            metadata={"trust_label": "email_provider_api"},
            updated_at="2026-06-10T12:00:00Z",
        )
        status, _, states = self.json_request("GET", "/api/connectors/state")
        self.assertEqual(status, 200)
        self.assertEqual(states[0]["connector"], "gmail_api")
        self.assertEqual(states[0]["cursor"], "history-123")
        self.assertEqual(states[0]["scopes"], ["https://www.googleapis.com/auth/gmail.readonly"])

    def test_scenario_apply_run_exposes_redacted_evidence_and_report(self) -> None:
        apply_scenario(self.paths, "opt_baseline")
        baseline_status, _, baseline_runs = self.json_request("POST", "/api/run?name=Demo%20OPT%20Case")
        self.assertEqual(baseline_status, 200)
        self.assertEqual(baseline_runs[0]["alert"]["level"], "baseline")

        scenario_status, _, scenarios = self.json_request("GET", "/api/scenarios?kind=opt")
        self.assertEqual(scenario_status, 200)
        self.assertTrue(any(item["id"] == "opt_action_required" for item in scenarios))

        run_status, _, result = self.json_request("POST", "/api/scenario?scenario=opt_action_required&run=1")
        self.assertEqual(run_status, 200)
        run = result["runs"][0]
        self.assertEqual(run["alert"]["level"], "critical")
        self.assertEqual(run["status"]["value"], "action_required")

        evidence_status, _, evidence = self.json_request("GET", f"/api/evidence/{run['run_id']}?redacted=1")
        self.assertEqual(evidence_status, 200)
        self.assertEqual(evidence["target_url"], "[REDACTED_URL]")
        self.assertNotIn("file://", json.dumps(evidence))

        report_status, report_headers, report_body = self.request("GET", f"/api/report/{run['run_id']}")
        report_html = report_body.decode("utf-8")
        self.assertEqual(report_status, 200)
        self.assertIn("text/html", report_headers["content-type"])
        self.assertIn("SentinelDesk Evidence Report", report_html)
        self.assertNotIn("file://", report_html)

        package_status, package_headers, package_body = self.request("GET", f"/api/package/{run['run_id']}")
        self.assertEqual(package_status, 200)
        self.assertEqual(package_headers["content-type"], "application/zip")
        self.assertIn("attachment;", package_headers["content-disposition"])
        self.assertIn(".share.zip", package_headers["content-disposition"])
        with zipfile.ZipFile(io.BytesIO(package_body)) as archive:
            names = set(archive.namelist())
            self.assertEqual(names, {"README.md", "manifest.json", "evidence.redacted.json", "report.html"})
            combined = "\n".join(archive.read(name).decode("utf-8") for name in sorted(names))
        self.assertIn("sentineldesk-redacted-evidence-v1", combined)
        self.assertIn("[REDACTED_URL]", combined)
        self.assertNotIn("file://", combined)


if __name__ == "__main__":
    unittest.main()
