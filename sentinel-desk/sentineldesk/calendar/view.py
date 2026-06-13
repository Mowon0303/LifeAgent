from __future__ import annotations

import re
from datetime import datetime
from typing import Any


_THREAD_PREFIX = re.compile(r"^\s*(re|fw|fwd|回复|答复|转发)\s*[:：]\s*", re.IGNORECASE)


def _normalize_title(title: str) -> str:
    text = str(title or "").strip()
    while True:
        stripped = _THREAD_PREFIX.sub("", text)
        if stripped == text:
            break
        text = stripped
    return " ".join(text.lower().split())


DATE_FORMATS = (
    "%Y-%m-%d",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",   # 14 July 2026
    "%d %b %Y",   # 14 Jul 2026
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
        date_key = parse_deadline_date(str(draft.get("date_text") or ""))
        # a deadline draft with no resolvable date is not a calendar event — skip it so
        # it is never shown on the board or offered as an "add to calendar" suggestion
        if not date_key:
            continue
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
                "date_key": date_key,
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
    items = _dedupe_calendar_items(items)
    items.sort(key=lambda item: (item["date_key"] or "9999-99-99", item["title"], item["event_id"]))
    return items


def _prefer(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
    """A confirmed event wins over a draft; otherwise the higher-confidence one wins."""
    cand_confirmed = candidate["approval_state"] == "approved"
    cur_confirmed = current["approval_state"] == "approved"
    if cand_confirmed != cur_confirmed:
        return cand_confirmed
    return float(candidate["confidence"]) > float(current["confidence"])


def _dedupe_calendar_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse events that describe the same deadline arriving repeatedly across a
    reply thread (same normalized subject + same date) into one event, merging their
    source ids. Prevents the calendar from showing one chip per reply email."""
    best: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for item in items:
        key = (_normalize_title(item["title"]), item["date_key"])
        existing = best.get(key)
        if existing is None:
            best[key] = item
            order.append(key)
            continue
        winner = dict(item if _prefer(item, existing) else existing)
        merged = list(dict.fromkeys([*existing["source_ids"], *item["source_ids"]]))
        winner["source_ids"] = merged
        winner["source_count"] = len(merged)
        best[key] = winner
    return [best[key] for key in order]


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
