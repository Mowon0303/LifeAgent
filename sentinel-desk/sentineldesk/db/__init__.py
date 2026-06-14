"""Local SQLite evidence store.

Historically this was a single ``db.py`` module; it is now a package split by
aggregate (one repository module per table group). The flat ``db.<func>`` call
surface is preserved by re-exporting every public symbol here, so callers keep
writing ``from sentineldesk import db; db.list_targets(paths)`` unchanged.
"""

from __future__ import annotations

from .base import (
    SCHEMA,
    connect,
    decode_row,
    decode_rows,
    init_db,
    open_db,
)
from .targets import get_target, list_targets, upsert_target
from .runs import (
    get_run,
    insert_run,
    insert_trace,
    latest_run,
    list_alerts,
    list_runs,
    list_traces,
)
from .email import list_email_facts, list_email_messages, upsert_email_message
from .calendar import (
    delete_stale_local_drafts,
    list_calendar_drafts,
    update_calendar_draft,
    update_calendar_draft_sync_state,
    upsert_calendar_draft,
)
from .audit import (
    approval_record_exists,
    delete_calendar_sync_approvals,
    get_audit_event,
    insert_approval_record,
    insert_audit_event,
    list_approval_records,
    list_audit_events,
)
from .reviews import (
    delete_task_review,
    get_task_review,
    list_task_reviews,
    upsert_task_review,
)
from .rag import (
    embedded_rag_source_ids,
    list_rag_chunks,
    list_rag_documents,
    upsert_rag_document,
)
from .connectors import (
    get_connector_state,
    get_integration_verification,
    insert_integration_verification,
    list_connector_states,
    list_integration_verifications,
    upsert_connector_state,
)
from .model_calls import insert_model_call, list_model_calls, model_calls_summary

__all__ = [
    # base
    "SCHEMA",
    "connect",
    "open_db",
    "init_db",
    "decode_row",
    "decode_rows",
    # targets
    "upsert_target",
    "list_targets",
    "get_target",
    # runs + traces
    "latest_run",
    "insert_run",
    "list_runs",
    "get_run",
    "list_alerts",
    "insert_trace",
    "list_traces",
    # email
    "upsert_email_message",
    "list_email_messages",
    "list_email_facts",
    # calendar drafts
    "upsert_calendar_draft",
    "list_calendar_drafts",
    "delete_stale_local_drafts",
    "update_calendar_draft",
    "update_calendar_draft_sync_state",
    # audit + approvals
    "insert_audit_event",
    "list_audit_events",
    "get_audit_event",
    "insert_approval_record",
    "list_approval_records",
    "delete_calendar_sync_approvals",
    "approval_record_exists",
    # task reviews
    "upsert_task_review",
    "get_task_review",
    "delete_task_review",
    "list_task_reviews",
    # rag
    "upsert_rag_document",
    "list_rag_documents",
    "embedded_rag_source_ids",
    "list_rag_chunks",
    # connectors + integration verifications
    "upsert_connector_state",
    "get_connector_state",
    "list_connector_states",
    "insert_integration_verification",
    "list_integration_verifications",
    "get_integration_verification",
    # model calls
    "insert_model_call",
    "list_model_calls",
    "model_calls_summary",
]
