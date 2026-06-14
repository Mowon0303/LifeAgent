"""HTTP handler core: response helpers and a route table that dispatches to the
domain handler functions. The per-endpoint logic lives in the ``handlers_*``
modules; this file stays small and only wires requests to them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import ParseResult, urlparse

from ..config import Paths, project_root
from . import handlers_calendar as cal
from . import handlers_daily_gmail as daily_gmail
from . import handlers_misc as misc
from . import handlers_monitor as monitor
from . import handlers_tasks as tasks

# A route handler takes the active request handler plus the parsed URL and writes
# the full response itself (so it can choose status codes and content types).
RouteHandler = Callable[["Handler", ParseResult], None]


@dataclass(frozen=True)
class Route:
    path: str
    handler: RouteHandler
    prefix: bool = False

    def matches(self, path: str) -> bool:
        return path == self.path or (self.prefix and path.startswith(self.path))


GET_ROUTES: list[Route] = [
    Route("/api/targets", monitor.handle_targets),
    Route("/api/runs", monitor.handle_runs),
    Route("/api/alerts", monitor.handle_alerts),
    Route("/api/scenarios", monitor.handle_scenarios),
    Route("/api/email/facts", misc.handle_email_facts),
    Route("/api/tasks", tasks.handle_tasks),
    Route("/api/tasks/review/history", tasks.handle_tasks_review_history),
    Route("/api/tasks/review/summary", tasks.handle_tasks_review_summary),
    Route("/api/tasks/evidence", tasks.handle_tasks_evidence),
    Route("/api/daily/summary", daily_gmail.handle_daily_summary),
    Route("/api/gmail/readiness", daily_gmail.handle_gmail_readiness),
    Route("/api/gmail/sync-diagnostics", daily_gmail.handle_gmail_sync_diagnostics),
    Route("/api/calendar/drafts", cal.handle_calendar_drafts),
    Route("/api/calendar/events", cal.handle_calendar_events),
    Route("/api/calendar/evidence", cal.handle_calendar_evidence),
    Route("/api/audit/events", misc.handle_audit_events),
    Route("/api/approvals", misc.handle_approvals),
    Route("/api/connectors/state", misc.handle_connectors_state),
    Route("/api/model/calls", misc.handle_model_calls),
    Route("/api/integrations/verifications", misc.handle_integration_verifications),
    Route("/api/rag/docs", misc.handle_rag_docs),
    Route("/api/rag/search", misc.handle_rag_search),
    Route("/api/evidence/", monitor.handle_evidence, prefix=True),
    Route("/api/report/", monitor.handle_report, prefix=True),
    Route("/api/package/", monitor.handle_package, prefix=True),
    Route("/api/traces/", monitor.handle_traces, prefix=True),
]

POST_ROUTES: list[Route] = [
    Route("/api/ask", misc.handle_ask),
    Route("/api/run", monitor.handle_run),
    Route("/api/scenario", monitor.handle_scenario),
    Route("/api/calendar/sync", cal.handle_calendar_sync),
    Route("/api/calendar/unconfirm", cal.handle_calendar_unconfirm),
    Route("/api/calendar/drafts/update", cal.handle_calendar_drafts_update),
    Route("/api/calendar/create", cal.handle_calendar_create),
    Route("/api/calendar/delete", cal.handle_calendar_delete),
    Route("/api/tasks/review/bulk", tasks.handle_tasks_review_bulk),
    Route("/api/tasks/review/undo", tasks.handle_tasks_review_undo),
    Route("/api/tasks/review", tasks.handle_tasks_review),
    Route("/api/daily/run", daily_gmail.handle_daily_run),
    Route("/api/gmail/sync", daily_gmail.handle_gmail_sync),
    Route("/api/retention/purge", misc.handle_retention_purge),
]

STATIC_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    paths: Paths

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def send_json(self, value: object, status: int = 200) -> None:
        payload = json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")
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

    def read_json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        for route in GET_ROUTES:
            if route.matches(parsed.path):
                route.handler(self, parsed)
                return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        for route in POST_ROUTES:
            if route.matches(parsed.path):
                route.handler(self, parsed)
                return
        self.send_json({"error": "not found"}, status=404)

    def _serve_static(self, path: str) -> None:
        static_root = project_root() / "sentineldesk" / "static"
        if path in {"/", "/calendar"}:
            file_path = static_root / "calendar.html"
        elif path in {"/ops", "/index.html"}:
            file_path = static_root / "index.html"
        else:
            file_path = static_root / path.lstrip("/")
        if file_path.exists() and file_path.is_file():
            content_type = STATIC_CONTENT_TYPES.get(file_path.suffix, "text/plain; charset=utf-8")
            self.send_text(file_path.read_text(encoding="utf-8"), content_type=content_type)
        else:
            self.send_json({"error": "not found"}, status=404)


def serve(paths: Paths, *, host: str = "127.0.0.1", port: int = 8787) -> None:
    Handler.paths = paths
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"SentinelDesk dashboard: http://{host}:{port}")
    server.serve_forever()
