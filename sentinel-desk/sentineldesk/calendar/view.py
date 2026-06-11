from __future__ import annotations

from datetime import datetime
from typing import Any


DATE_FORMATS = (
    "%Y-%m-%d",
    "%B %d, %Y",
    "%b %d, %Y",
    "%m/%d/%Y",
    "%m/%d/%y",
)


def parse_deadline_date(value: str) -> str:
    text = " ".join(str(value or "").replace(",", ", ").split())
    if not text:
        return ""
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def build_calendar_items(drafts: list[dict[str, Any]], approvals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    approved_event_ids = _approved_event_ids(approvals)
    items: list[dict[str, Any]] = []
    for draft in drafts:
        event_id = str(draft.get("event_id") or "")
        sync_state = str(draft.get("sync_state") or "local_draft")
        status = str(draft.get("status") or "draft")
        confidence = float(draft.get("confidence") or 0.0)
        approval_state = "approved" if event_id in approved_event_ids or sync_state != "local_draft" else "draft"
        source_ids = [str(item) for item in draft.get("source_ids", [])]
        items.append(
            {
                "event_id": event_id,
                "title": str(draft.get("title") or ""),
                "date_text": str(draft.get("date_text") or ""),
                "date_key": parse_deadline_date(str(draft.get("date_text") or "")),
                "severity": str(draft.get("severity") or "medium"),
                "confidence": confidence,
                "status": status,
                "sync_state": sync_state,
                "approval_state": approval_state,
                "uncertain": confidence < 0.8 or status == "uncertain",
                "source_ids": source_ids,
                "source_trust": _source_trust(source_ids, str(draft.get("evidence_uri") or "")),
                "source_count": len(source_ids),
                "evidence_uri": str(draft.get("evidence_uri") or ""),
                "reminders": list(draft.get("reminders", [])),
            }
        )
    items.sort(key=lambda item: (item["date_key"] or "9999-99-99", item["title"], item["event_id"]))
    return items


def _approved_event_ids(approvals: list[dict[str, Any]]) -> set[str]:
    event_ids: set[str] = set()
    for approval in approvals:
        if approval.get("action") != "calendar.sync":
            continue
        metadata = approval.get("metadata", {})
        if not isinstance(metadata, dict):
            continue
        for event_id in metadata.get("event_ids", []):
            if event_id:
                event_ids.add(str(event_id))
    return event_ids


def _source_trust(source_ids: list[str], evidence_uri: str) -> str:
    joined = " ".join([*source_ids, evidence_uri]).lower()
    if "portal" in joined or "run_" in joined:
        return "portal_verified"
    if "gmail:" in joined or "email:" in joined:
        return "email_evidence"
    if "rag:" in joined or "doc:" in joined:
        return "trusted_doc_context"
    return "local_evidence"
