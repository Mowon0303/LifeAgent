from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import db
from .agent.model import load_model_provider
from .agent.tools import default_tool_registry
from .agent.workflow import answer_with_workflow
from .config import Paths, ensure_config, ensure_dirs, project_root, seed_demo_fixtures
from .daily import build_daily_landing_summary
from .email.connectors import EmailSyncRequest, LocalJsonEmailConnector
from .email.ingest import ingest_messages, stored_email_messages
from .scenarios import apply_scenario


@dataclass(frozen=True)
class AcceptanceCheck:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": "passed" if self.passed else "failed",
            "detail": self.detail,
        }


def run_first_run_acceptance(paths: Paths, *, sample_email_json: str | Path | None = None, port: int = 8787) -> dict[str, Any]:
    """Prepare and verify the local synthetic first-run experience.

    This path intentionally uses only local fixtures. It must not call Gmail,
    submit portal changes, or write to external calendars.
    """
    ensure_dirs(paths)
    ensure_config(paths)
    db.init_db(paths)
    copied = seed_demo_fixtures(paths)
    for scenario in ("opt_baseline", "appointment_baseline", "lease_baseline"):
        apply_scenario(paths, scenario)

    sample_path = Path(sample_email_json) if sample_email_json else project_root() / "fixtures" / "ui" / "sample_emails.json"
    connector = LocalJsonEmailConnector(str(sample_path))
    messages = list(connector.search(EmailSyncRequest(query="", limit=50)).messages)
    ingest_summary = ingest_messages(paths, messages)
    sync_summary = {
        "mode": "local_json",
        "external_network": False,
        "source": _display_path(sample_path),
        "query": "",
        **ingest_summary,
    }
    summary = build_daily_landing_summary(paths, sync_summary=sync_summary, task_limit=12, calendar_limit=20, actor="acceptance")
    answer = answer_with_workflow(
        "what is my earliest deadline?",
        provider=load_model_provider(paths),
        messages=stored_email_messages(paths),
        registry=default_tool_registry(paths),
        paths=paths,
    )
    targets = db.list_targets(paths)
    events = db.list_audit_events(paths, limit=5)
    calendar_items = list(summary["calendar"]["items"])
    task_queue = list(summary["tasks"]["queue"])
    task_kinds = {str(task.get("kind") or "") for task in task_queue}
    calendar_dates = {str(item.get("date_key") or "") for item in calendar_items}
    static_calendar = project_root() / "sentineldesk" / "static" / "calendar.html"
    static_html = static_calendar.read_text(encoding="utf-8") if static_calendar.exists() else ""

    checks = [
        AcceptanceCheck("local_fixture_available", sample_path.exists(), f"fixture={_display_path(sample_path)}"),
        AcceptanceCheck("demo_targets_seeded", len(targets) >= 3, f"targets={len(targets)}, fixtures_copied={copied}"),
        AcceptanceCheck("local_email_loaded", summary["email"]["stored_message_count"] >= 4, f"stored_messages={summary['email']['stored_message_count']}"),
        AcceptanceCheck("facts_extracted", sum(summary["email"]["fact_counts"].values()) >= 8, f"facts={summary['email']['fact_counts']}"),
        AcceptanceCheck("review_queue_ready", summary["tasks"]["queue_count"] >= 7, f"queue_count={summary['tasks']['queue_count']}"),
        AcceptanceCheck("task_kinds_ready", {"deadline", "amount", "action"}.issubset(task_kinds), f"kinds={sorted(task_kinds)}"),
        AcceptanceCheck("calendar_drafts_ready", summary["calendar"]["pending_count"] >= 3, f"pending={summary['calendar']['pending_count']}"),
        AcceptanceCheck(
            "calendar_dates_visible",
            {"2026-07-01", "2026-07-02", "2026-09-03"}.issubset(calendar_dates),
            f"date_keys={sorted(calendar_dates)}",
        ),
        AcceptanceCheck("gmail_readiness_local_only", _gmail_readiness_ok(summary), f"status={summary['gmail_readiness']['status']}"),
        AcceptanceCheck(
            "gmail_diagnostics_local_only",
            not summary["gmail_sync_diagnostics"]["external_network"] and not summary["gmail_sync_diagnostics"]["external_writes_performed"],
            f"status={summary['gmail_sync_diagnostics']['status']}",
        ),
        AcceptanceCheck("tool_first_ask_ready", _ask_ok(answer), f"intent={answer.intent.value}, citations={len(answer.citations)}"),
        AcceptanceCheck("external_boundaries_clear", _external_boundaries_ok(summary), "no external network/write path used"),
        AcceptanceCheck("audit_written", bool(events and events[0]["action"] == "daily.run"), f"latest_action={events[0]['action'] if events else ''}"),
        AcceptanceCheck("calendar_ui_wired", _calendar_ui_wired(static_html), "calendar assistant static contract markers present"),
    ]
    status = "passed" if all(check.passed for check in checks) else "failed"
    return {
        "status": status,
        "mode": "first_run_acceptance",
        "external_network": False,
        "external_writes_performed": False,
        "home": "[REDACTED_PATH]",
        "fixture": _display_path(sample_path),
        "dashboard": {
            "calendar_url": f"http://127.0.0.1:{port}/",
            "ops_url": f"http://127.0.0.1:{port}/ops",
            "serve_command": f"python3 -B -m sentineldesk --home <home> serve --port {port}",
        },
        "summary": {
            "stored_messages": summary["email"]["stored_message_count"],
            "fact_counts": summary["email"]["fact_counts"],
            "task_queue_count": summary["tasks"]["queue_count"],
            "task_kinds": sorted(task_kinds),
            "calendar_pending_count": summary["calendar"]["pending_count"],
            "calendar_dates": sorted(calendar_dates),
            "gmail_readiness_status": summary["gmail_readiness"]["status"],
            "gmail_sync_diagnostics_status": summary["gmail_sync_diagnostics"]["status"],
        },
        "ask_smoke": {
            "question": "what is my earliest deadline?",
            "intent": answer.intent.value,
            "confidence": answer.confidence,
            "uncertain": answer.uncertain,
            "tool_calls": list(answer.tool_calls),
            "citation_count": len(answer.citations),
            "answer": answer.answer,
        },
        "checks": [check.to_dict() for check in checks],
    }


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root()))
    except ValueError:
        return "[REDACTED_PATH]"


def _gmail_readiness_ok(summary: dict[str, Any]) -> bool:
    readiness = summary["gmail_readiness"]
    return (
        readiness["status"] in {"needs_oauth", "needs_dependency", "needs_sync", "ready"}
        and readiness["has_local_evidence"]
        and not readiness["external_network"]
        and not readiness["external_writes_performed"]
    )


def _ask_ok(answer: Any) -> bool:
    return (
        answer.intent.value == "latest_deadline"
        and "search_latest_email" in answer.tool_calls
        and len(answer.citations) >= 1
        and "07/01/2026" in answer.answer
    )


def _external_boundaries_ok(summary: dict[str, Any]) -> bool:
    return (
        not summary["sync"]["external_network"]
        and not summary["safety"]["external_writes_performed"]
        and summary["safety"]["calendar_writes_require_confirmation"]
        and not summary["safety"]["raw_secret_values_included"]
    )


def _calendar_ui_wired(html: str) -> bool:
    required_markers = [
        "/api/daily/summary",
        "/api/gmail/sync?confirm=1",
        'data-act="gmail-sync"',
        'data-act="task-view"',
        'data-act="task-bulk-done"',
        'id="taskSessionSummary"',
    ]
    return all(marker in html for marker in required_markers)
