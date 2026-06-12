from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db
from .agent.model import load_model_provider
from .agent.rag_index import search_index
from .agent.tools import default_tool_registry
from .agent.workflow import answer_with_workflow
from .calendar.adapters import IcsFileCalendarAdapter, sync_calendar_draft
from .calendar.models import CalendarDraft
from .calendar.source import events_from_calendar_rows
from .calendar.view import build_calendar_items
from .config import Paths, project_root
from .daily import build_daily_landing_summary
from .email.ingest import stored_email_messages
from .extract import utc_now
from .gmail_readiness import build_gmail_readiness
from .monitor import run_all
from .reports import package_path_for, redact_data, write_evidence_package
from .retention import plan_purge, purge, result_to_dict
from .scenarios import apply_scenario, list_scenarios
from .tasks import (
    build_review_receipt_summary,
    bulk_review_tasks,
    list_review_history,
    list_tasks,
    review_task,
    task_evidence,
    undo_task_review,
)


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    paths: Paths

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def send_json(self, value: object, status: int = 200) -> None:
        payload = json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_text(self, value: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        payload = value.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_file(self, path: Path, *, content_type: str, download_name: str | None = None) -> None:
        payload = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/targets":
            self.send_json(db.list_targets(self.paths))
            return
        if path == "/api/runs":
            self.send_json(db.list_runs(self.paths, limit=100))
            return
        if path == "/api/alerts":
            self.send_json(db.list_alerts(self.paths, limit=100))
            return
        if path == "/api/email/facts":
            query = parse_qs(parsed.query)
            self.send_json(db.list_email_facts(self.paths, kind=query.get("kind", [None])[0], limit=100))
            return
        if path == "/api/tasks":
            query = parse_qs(parsed.query)
            try:
                self.send_json(
                    list_tasks(
                        self.paths,
                        status=query.get("status", [None])[0],
                        kind=query.get("kind", [None])[0],
                        sort=query.get("sort", [None])[0],
                        view=query.get("view", ["all"])[0],
                        limit=_query_int(query, "limit", 100),
                    )
                )
            except ValueError as error:
                self.send_json({"error": str(error)}, status=400)
            return
        if path == "/api/tasks/review/history":
            query = parse_qs(parsed.query)
            self.send_json(
                {
                    "history": list_review_history(self.paths, limit=_query_int(query, "limit", 20)),
                    "external_network": False,
                    "external_writes_performed": False,
                }
            )
            return
        if path == "/api/tasks/review/summary":
            query = parse_qs(parsed.query)
            self.send_json(
                build_review_receipt_summary(
                    self.paths,
                    limit=_query_int(query, "limit", 50),
                    recent_limit=_query_int(query, "recent_limit", 5),
                )
            )
            return
        if path == "/api/tasks/evidence":
            query = parse_qs(parsed.query)
            task_id = query.get("task_id", [""])[0]
            if not task_id:
                self.send_json({"error": "task_id query parameter required"}, status=400)
                return
            try:
                self.send_json(task_evidence(self.paths, task_id=task_id))
            except ValueError as error:
                self.send_json({"error": str(error)}, status=404)
            return
        if path == "/api/daily/summary":
            query = parse_qs(parsed.query)
            self.send_json(
                build_daily_landing_summary(
                    self.paths,
                    task_limit=_query_int(query, "task_limit", 12),
                    calendar_limit=_query_int(query, "calendar_limit", 20),
                    actor="dashboard",
                    record_audit=False,
                    account_id=query.get("account", ["default"])[0],
                    google_credentials_env=query.get("google_credentials_env", ["SENTINEL_GOOGLE_CREDENTIALS_JSON"])[0],
                    google_token_env=query.get("google_token_env", ["SENTINEL_GOOGLE_TOKEN_JSON"])[0],
                )
            )
            return
        if path == "/api/gmail/readiness":
            query = parse_qs(parsed.query)
            self.send_json(
                build_gmail_readiness(
                    self.paths,
                    account_id=query.get("account", ["default"])[0],
                    credentials_env=query.get("google_credentials_env", ["SENTINEL_GOOGLE_CREDENTIALS_JSON"])[0],
                    token_env=query.get("google_token_env", ["SENTINEL_GOOGLE_TOKEN_JSON"])[0],
                )
            )
            return
        if path == "/api/calendar/drafts":
            self.send_json(db.list_calendar_drafts(self.paths, limit=100))
            return
        if path == "/api/calendar/events":
            self.send_json(
                build_calendar_items(
                    db.list_calendar_drafts(self.paths, limit=200),
                    db.list_approval_records(self.paths, limit=200),
                )
            )
            return
        if path == "/api/audit/events":
            self.send_json(db.list_audit_events(self.paths, limit=100))
            return
        if path == "/api/approvals":
            self.send_json(db.list_approval_records(self.paths, limit=100))
            return
        if path == "/api/connectors/state":
            self.send_json(db.list_connector_states(self.paths, limit=100))
            return
        if path == "/api/model/calls":
            self.send_json(
                {
                    "summary": db.model_calls_summary(self.paths),
                    "calls": db.list_model_calls(self.paths, limit=100),
                }
            )
            return
        if path == "/api/integrations/verifications":
            self.send_json(db.list_integration_verifications(self.paths, limit=50))
            return
        if path == "/api/rag/docs":
            self.send_json(db.list_rag_documents(self.paths, limit=100))
            return
        if path == "/api/rag/search":
            query = parse_qs(parsed.query)
            results = search_index(self.paths, query.get("q", [""])[0], limit=10)
            self.send_json([result.__dict__ for result in results])
            return
        if path == "/api/scenarios":
            query = parse_qs(parsed.query)
            self.send_json(list_scenarios(kind=query.get("kind", [None])[0]))
            return
        if path.startswith("/api/evidence/"):
            run_id = path.rsplit("/", 1)[-1]
            run = db.get_run(self.paths, run_id)
            if not run:
                self.send_json({"error": "not found"}, status=404)
                return
            evidence_path = Path(run["evidence"]["path"])
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            query = parse_qs(parsed.query)
            self.send_json(redact_data(evidence) if query.get("redacted", ["0"])[0] in {"1", "true", "yes"} else evidence)
            return
        if path.startswith("/api/report/"):
            run_id = path.rsplit("/", 1)[-1]
            run = db.get_run(self.paths, run_id)
            if not run:
                self.send_json({"error": "not found"}, status=404)
                return
            report_path = Path(run["evidence"].get("report_path", ""))
            if not report_path.exists():
                self.send_json({"error": "report not found"}, status=404)
                return
            self.send_text(report_path.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8")
            return
        if path.startswith("/api/package/"):
            run_id = path.rsplit("/", 1)[-1]
            run = db.get_run(self.paths, run_id)
            if not run:
                self.send_json({"error": "not found"}, status=404)
                return
            evidence_path = Path(run["evidence"]["path"])
            if not evidence_path.exists():
                self.send_json({"error": "evidence not found"}, status=404)
                return
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            package_path = write_evidence_package(package_path_for(evidence_path), evidence)
            self.send_file(
                package_path,
                content_type="application/zip",
                download_name=package_path.name,
            )
            return
        if path.startswith("/api/traces/"):
            run_id = path.rsplit("/", 1)[-1]
            self.send_json(db.list_traces(self.paths, run_id))
            return

        static_root = project_root() / "sentineldesk" / "static"
        if path in {"/", "/calendar"}:
            file_path = static_root / "calendar.html"
        elif path in {"/ops", "/index.html"}:
            file_path = static_root / "index.html"
        else:
            file_path = static_root / path.lstrip("/")
        if file_path.exists() and file_path.is_file():
            content_types = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".svg": "image/svg+xml; charset=utf-8",
            }
            content_type = content_types.get(file_path.suffix, "text/plain; charset=utf-8")
            self.send_text(file_path.read_text(encoding="utf-8"), content_type=content_type)
        else:
            self.send_json({"error": "not found"}, status=404)

    def read_json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/ask":
            body = self.read_json_body()
            question = str(body.get("question") or "").strip()
            if not question:
                self.send_json({"error": "question field required"}, status=400)
                return
            try:
                answer = answer_with_workflow(
                    question,
                    provider=load_model_provider(self.paths),
                    messages=stored_email_messages(self.paths),
                    registry=default_tool_registry(self.paths),
                    paths=self.paths,
                )
                self.send_json(
                    {
                        "intent": answer.intent.value,
                        "answer": answer.answer,
                        "confidence": answer.confidence,
                        "uncertain": answer.uncertain,
                        "requires_confirmation": answer.requires_confirmation,
                        "tool_calls": list(answer.tool_calls),
                        "citations": [citation.__dict__ for citation in answer.citations],
                        "metadata": answer.metadata,
                    }
                )
            except Exception as error:
                self.send_json({"error": str(error)}, status=500)
            return
        if parsed.path == "/api/run":
            query = parse_qs(parsed.query)
            name = query.get("name", [None])[0]
            try:
                self.send_json(run_all(self.paths, name=name))
            except Exception as error:
                self.send_json({"error": str(error)}, status=500)
            return
        if parsed.path == "/api/scenario":
            query = parse_qs(parsed.query)
            scenario_id = query.get("scenario", [None])[0]
            target_name = query.get("target", [None])[0]
            run_after_apply = query.get("run", ["0"])[0] in {"1", "true", "yes"}
            if not scenario_id:
                self.send_json({"error": "scenario query parameter required"}, status=400)
                return
            try:
                target = apply_scenario(self.paths, scenario_id, target_name=target_name)
                runs = run_all(self.paths, name=target["name"]) if run_after_apply else []
                self.send_json({"target": target, "runs": runs})
            except Exception as error:
                self.send_json({"error": str(error)}, status=500)
            return
        if parsed.path == "/api/calendar/sync":
            query = parse_qs(parsed.query)
            confirmed = query.get("confirm", ["0"])[0] in {"1", "true", "yes"}
            event_id = query.get("event_id", [None])[0]
            destination = query.get("destination", ["ics"])[0]
            if destination != "ics":
                self.send_json({"error": "only local ICS export is available without an authenticated calendar client"}, status=400)
                return
            try:
                events = events_from_calendar_rows(db.list_calendar_drafts(self.paths, limit=200), event_id=event_id)
                if not events:
                    self.send_json({"error": "no calendar drafts found"}, status=404)
                    return
                draft = CalendarDraft(events=tuple(events))
                output_path = self.paths.artifacts / "calendar" / "lifeagent-deadlines.ics"
                result = sync_calendar_draft(
                    self.paths,
                    draft,
                    IcsFileCalendarAdapter(output_path),
                    confirmed=confirmed,
                    confirmation_id=query.get("confirmation_id", [""])[0] if confirmed else "",
                    actor="dashboard",
                )
                if result.allowed:
                    for synced_event_id in result.event_ids:
                        db.update_calendar_draft_sync_state(
                            self.paths,
                            event_id=synced_event_id,
                            sync_state="ics_exported",
                            status="synced",
                            updated_at=utc_now(),
                        )
                self.send_json(result.__dict__)
            except Exception as error:
                self.send_json({"error": str(error)}, status=500)
            return
        if parsed.path == "/api/calendar/drafts/update":
            query = parse_qs(parsed.query)
            event_id = query.get("event_id", [""])[0]
            if not event_id:
                self.send_json({"error": "event_id query parameter required"}, status=400)
                return
            try:
                updated_at = utc_now()
                updated = db.update_calendar_draft(
                    self.paths,
                    event_id=event_id,
                    title=query.get("title", [None])[0],
                    date_text=query.get("date", [None])[0],
                    severity=query.get("severity", [None])[0],
                    status="draft",
                    sync_state="local_draft",
                    updated_at=updated_at,
                )
                if not updated:
                    self.send_json({"error": "calendar draft not found", "event_id": event_id}, status=404)
                    return
                db.insert_audit_event(
                    self.paths,
                    action="calendar.edit",
                    actor="dashboard",
                    subject=event_id,
                    capability="calendar_draft",
                    side_effect="local_db_write",
                    allowed=True,
                    confirmation_id="",
                    metadata={
                        "title": updated.get("title"),
                        "date_text": updated.get("date_text"),
                        "severity": updated.get("severity"),
                        "sync_state": updated.get("sync_state"),
                        "external_write": False,
                    },
                    created_at=updated_at,
                )
                self.send_json({"updated": updated, "external_write": False})
            except Exception as error:
                self.send_json({"error": str(error)}, status=500)
            return
        if parsed.path == "/api/tasks/review/bulk":
            query = parse_qs(parsed.query)
            body = self.read_json_body()
            task_ids = body.get("task_ids") if isinstance(body.get("task_ids"), list) else query.get("task_id", [])
            task_ids = [str(task_id) for task_id in task_ids if str(task_id)]
            filter_payload = body.get("filter") if isinstance(body.get("filter"), dict) else {}
            status = str(body.get("status") or query.get("status", [""])[0])
            if not status:
                self.send_json({"error": "status field required"}, status=400)
                return
            try:
                result = bulk_review_tasks(
                    self.paths,
                    task_ids=task_ids,
                    status=status,
                    kind=str(filter_payload.get("kind") or query.get("kind", ["all"])[0]),
                    status_filter=str(filter_payload.get("status") or query.get("filter_status", ["active"])[0]),
                    limit=_query_int(query, "limit", _body_int(body, "limit", 100)),
                    note=str(body.get("note") or query.get("note", [""])[0]),
                    actor="dashboard",
                    confirmed=_truthy(body.get("confirm", query.get("confirm", ["0"])[0])),
                    confirmation_id=str(body.get("confirmation_id") or query.get("confirmation_id", [""])[0]),
                )
                self.send_json(result.__dict__)
            except ValueError as error:
                self.send_json({"error": str(error)}, status=400)
            except Exception as error:
                self.send_json({"error": str(error)}, status=500)
            return
        if parsed.path == "/api/tasks/review/undo":
            query = parse_qs(parsed.query)
            body = self.read_json_body()
            audit_id_raw = body.get("audit_id") or query.get("audit_id", [""])[0]
            if not audit_id_raw:
                self.send_json({"error": "audit_id field required"}, status=400)
                return
            try:
                result = undo_task_review(
                    self.paths,
                    audit_id=int(audit_id_raw),
                    actor="dashboard",
                    confirmed=_truthy(body.get("confirm", query.get("confirm", ["0"])[0])),
                    confirmation_id=str(body.get("confirmation_id") or query.get("confirmation_id", [""])[0]),
                )
                self.send_json(result.__dict__)
            except ValueError as error:
                self.send_json({"error": str(error)}, status=400)
            except Exception as error:
                self.send_json({"error": str(error)}, status=500)
            return
        if parsed.path == "/api/tasks/review":
            query = parse_qs(parsed.query)
            task_id = query.get("task_id", [""])[0]
            status = query.get("status", [""])[0]
            if not task_id:
                self.send_json({"error": "task_id query parameter required"}, status=400)
                return
            if not status:
                self.send_json({"error": "status query parameter required"}, status=400)
                return
            try:
                result = review_task(
                    self.paths,
                    task_id=task_id,
                    status=status,
                    note=query.get("note", [""])[0],
                    actor="dashboard",
                )
                self.send_json(
                    {
                        "task_id": result.task_id,
                        "status": result.status,
                        "note": result.note,
                        "actor": result.actor,
                        "updated_at": result.updated_at,
                        "task": result.task,
                    }
                )
            except ValueError as error:
                self.send_json({"error": str(error)}, status=400)
            except Exception as error:
                self.send_json({"error": str(error)}, status=500)
            return
        if parsed.path == "/api/daily/run":
            query = parse_qs(parsed.query)
            self.send_json(
                build_daily_landing_summary(
                    self.paths,
                    task_limit=_query_int(query, "task_limit", 12),
                    calendar_limit=_query_int(query, "calendar_limit", 20),
                    actor="dashboard",
                    record_audit=True,
                    account_id=query.get("account", ["default"])[0],
                    google_credentials_env=query.get("google_credentials_env", ["SENTINEL_GOOGLE_CREDENTIALS_JSON"])[0],
                    google_token_env=query.get("google_token_env", ["SENTINEL_GOOGLE_TOKEN_JSON"])[0],
                )
            )
            return
        if parsed.path == "/api/retention/purge":
            query = parse_qs(parsed.query)
            before = query.get("before", [""])[0]
            sources = tuple(query.get("source", [])) or ("email", "calendar", "tasks", "audit", "approvals")
            confirmed = query.get("confirm", ["0"])[0] in {"1", "true", "yes"}
            if not before:
                self.send_json({"error": "before query parameter required"}, status=400)
                return
            try:
                result = (
                    purge(self.paths, before=before, sources=sources, confirmed=True, actor="dashboard")
                    if confirmed
                    else plan_purge(self.paths, before=before, sources=sources)
                )
                self.send_json(result_to_dict(result))
            except ValueError as error:
                self.send_json({"error": str(error)}, status=400)
            except Exception as error:
                self.send_json({"error": str(error)}, status=500)
            return
        self.send_json({"error": "not found"}, status=404)


def serve(paths: Paths, *, host: str = "127.0.0.1", port: int = 8787) -> None:
    Handler.paths = paths
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"SentinelDesk dashboard: http://{host}:{port}")
    server.serve_forever()


def _query_int(query: dict[str, list[str]], name: str, default: int) -> int:
    try:
        return max(0, int(query.get(name, [str(default)])[0]))
    except (TypeError, ValueError):
        return default


def _body_int(body: dict[str, object], name: str, default: int) -> int:
    try:
        return max(0, int(body.get(name, default)))
    except (TypeError, ValueError):
        return default


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "y", "on"}
