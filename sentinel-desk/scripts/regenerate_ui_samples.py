"""Regenerate the committed UI sample responses in ``fixtures/ui/``.

The samples are documentation of the API shapes (see ``docs/UI_CONTRACT.md``);
``tests/test_ui_contract.py::UiFixtureSampleTests`` asserts they still match the
live endpoints. Regenerating them by hand is how they drift, so do it with:

    python -B scripts/regenerate_ui_samples.py

Runs entirely on the synthetic ``fixtures/ui/sample_emails.json`` inbox in a
throwaway home: no network, no external writes, no real mail.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentineldesk import db  # noqa: E402
from sentineldesk.agent.model import load_model_provider  # noqa: E402
from sentineldesk.agent.tools import default_tool_registry  # noqa: E402
from sentineldesk.agent.workflow import answer_with_workflow  # noqa: E402
from sentineldesk.calendar.view import build_calendar_items  # noqa: E402
from sentineldesk.config import ensure_config, ensure_dirs, get_paths, project_root  # noqa: E402
from sentineldesk.daily import build_daily_landing_summary  # noqa: E402
from sentineldesk.email.ingest import ingest_messages, load_fixture_email_json, stored_email_messages  # noqa: E402

FIXTURES_UI = project_root() / "fixtures" / "ui"
ASK_QUESTION = "What is my latest deadline?"


def _write(name: str, payload: object) -> None:
    path = FIXTURES_UI / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(project_root())}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        paths = get_paths(tmp)
        ensure_dirs(paths)
        ensure_config(paths)
        db.init_db(paths)
        messages = load_fixture_email_json(FIXTURES_UI / "sample_emails.json")
        ingest_messages(paths, messages)

        _write(
            "calendar_events.sample.json",
            build_calendar_items(
                db.list_calendar_drafts(paths, limit=200),
                db.list_approval_records(paths, limit=200),
            ),
        )
        from sentineldesk.tasks import list_tasks

        _write("tasks.sample.json", list_tasks(paths, limit=100))
        _write(
            "daily_summary.sample.json",
            build_daily_landing_summary(paths, task_limit=0, calendar_limit=0, actor="docs", record_audit=False),
        )
        answer = answer_with_workflow(
            ASK_QUESTION,
            provider=load_model_provider(paths),
            messages=stored_email_messages(paths),
            registry=default_tool_registry(paths),
            paths=paths,
        )
        _write(
            "ask_answer.sample.json",
            {
                "intent": answer.intent.value,
                "answer": answer.answer,
                "confidence": answer.confidence,
                "uncertain": answer.uncertain,
                "requires_confirmation": answer.requires_confirmation,
                "tool_calls": list(answer.tool_calls),
                "citations": [citation.__dict__ for citation in answer.citations],
                "metadata": answer.metadata,
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
