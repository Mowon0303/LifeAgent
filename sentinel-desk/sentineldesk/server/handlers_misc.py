"""Route handlers for email facts, RAG, the assistant ask loop, ledgers, and retention."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from .. import db
from ..agent.model import load_model_provider
from ..agent.rag_index import search_index
from ..agent.tools import default_tool_registry
from ..agent.workflow import answer_with_workflow
from ..calendar.view import build_calendar_items
from ..email.ingest import stored_email_messages
from ..retention import plan_purge, purge, result_to_dict
from .helpers import sanitize_ask_history

if TYPE_CHECKING:  # pragma: no cover - typing only
    from urllib.parse import ParseResult

    from .app import Handler


def handle_email_facts(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    h.send_json(db.list_email_facts(h.paths, kind=query.get("kind", [None])[0], limit=100))


def handle_audit_events(h: "Handler", parsed: "ParseResult") -> None:
    h.send_json(db.list_audit_events(h.paths, limit=100))


def handle_approvals(h: "Handler", parsed: "ParseResult") -> None:
    h.send_json(db.list_approval_records(h.paths, limit=100))


def handle_connectors_state(h: "Handler", parsed: "ParseResult") -> None:
    h.send_json(db.list_connector_states(h.paths, limit=100))


def handle_model_calls(h: "Handler", parsed: "ParseResult") -> None:
    h.send_json(
        {
            "summary": db.model_calls_summary(h.paths),
            "calls": db.list_model_calls(h.paths, limit=100),
        }
    )


def handle_integration_verifications(h: "Handler", parsed: "ParseResult") -> None:
    h.send_json(db.list_integration_verifications(h.paths, limit=50))


def handle_rag_docs(h: "Handler", parsed: "ParseResult") -> None:
    h.send_json(db.list_rag_documents(h.paths, limit=100))


def handle_rag_search(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    results = search_index(h.paths, query.get("q", [""])[0], limit=10)
    h.send_json([result.__dict__ for result in results])


def handle_ask(h: "Handler", parsed: "ParseResult") -> None:
    body = h.read_json_body()
    question = str(body.get("question") or "").strip()
    if not question:
        h.send_json({"error": "question field required"}, status=400)
        return
    raw_history = body.get("history") if isinstance(body, dict) else None
    history = sanitize_ask_history(raw_history)
    # The task overview answers from accepted calendar deadlines (facts), not raw
    # extraction — so build the same calendar view the board uses and pass it in.
    calendar_items = build_calendar_items(
        db.list_calendar_drafts(h.paths, limit=200),
        db.list_approval_records(h.paths, limit=200),
    )
    try:
        answer = answer_with_workflow(
            question,
            provider=load_model_provider(h.paths),
            messages=stored_email_messages(h.paths),
            registry=default_tool_registry(h.paths),
            paths=h.paths,
            history=history,
            calendar=calendar_items,
        )
        h.send_json(
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
    except Exception as error:  # noqa: BLE001 - fail-soft API surface
        h.send_json({"error": str(error)}, status=500)


def handle_retention_purge(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    before = query.get("before", [""])[0]
    sources = tuple(query.get("source", [])) or ("email", "calendar", "tasks", "audit", "approvals")
    confirmed = query.get("confirm", ["0"])[0] in {"1", "true", "yes"}
    if not before:
        h.send_json({"error": "before query parameter required"}, status=400)
        return
    try:
        result = (
            purge(h.paths, before=before, sources=sources, confirmed=True, actor="dashboard")
            if confirmed
            else plan_purge(h.paths, before=before, sources=sources)
        )
        h.send_json(result_to_dict(result))
    except ValueError as error:
        h.send_json({"error": str(error)}, status=400)
    except Exception as error:  # noqa: BLE001 - fail-soft API surface
        h.send_json({"error": str(error)}, status=500)
