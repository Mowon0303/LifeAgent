"""Priority scoring: turn a task dict into a score, band, and reason list."""

from __future__ import annotations

import re
from typing import Any

from .common import _confidence_value, _has_payment_context, _task_due_key


AMOUNT_RE = re.compile(r"[$€£¥￥]?\s*(\d[\d,]*(?:\.\d{1,2})?)")


def _apply_priority(task: dict[str, Any]) -> None:
    score = 0
    reasons: list[str] = []
    status = str(task.get("status") or "new")
    kind = str(task.get("kind") or "")
    severity = str(task.get("severity") or "medium")
    confidence = _confidence_value(task.get("confidence"))

    # A human-set "needs_verification" status is a real obligation signal (a
    # person flagged that work is owed). Automatic uncertainty is handled lower
    # down — as a reason only, never a score boost — so a low-confidence promo
    # cannot inflate itself into the high band.
    if status == "needs_verification":
        score += 100
        reasons.append("needs_verification_status")
    elif status == "new":
        score += 25
        reasons.append("new_item")
    elif status == "reviewed":
        score += 5
        reasons.append("already_reviewed")
    elif status in {"done", "ignored"}:
        reasons.append("closed")

    severity_score = {"critical": 75, "high": 60, "medium": 30, "low": 10}.get(severity, 20)
    score += severity_score
    reasons.append(f"{severity if severity in {'critical', 'high', 'medium', 'low'} else 'unknown'}_severity")

    if kind == "deadline":
        score += 35
        reasons.append("deadline")
    elif kind == "amount":
        score += 25
        reasons.append("amount")
    elif kind == "action":
        score += 20
        reasons.append("action")

    # Obligation signals — a concrete commitment, not "the extractor is unsure".
    # Only these (or a human needs_verification flag) earn the high band, so the
    # high lane is reserved for real dates and money owed rather than every
    # imperative verb the extractor caught in a newsletter.
    has_obligation = status == "needs_verification"
    due_key = _task_due_key(task)
    if kind == "deadline" and due_key:
        score += 15
        reasons.append("dated_deadline")
        has_obligation = True
    elif kind == "deadline" and task.get("due_date"):
        score += 10
        reasons.append("relative_or_unparsed_deadline")
        has_obligation = True

    if kind == "amount":
        amount = _max_amount(task)
        if amount >= 1000:
            score += 20
            reasons.append("large_amount")
            has_obligation = True
        elif amount >= 100:
            score += 10
            reasons.append("meaningful_amount")
            has_obligation = True
    if _has_payment_context(task):
        score += 15
        reasons.append("payment_context")
    if _has_action_context(task):
        score += 10
        reasons.append("action_context")

    # Uncertainty is recorded for the reviewer and the needs-verification view,
    # but it no longer raises priority: a low-confidence item should sink, not
    # surface. (Previously these two added +70 and pushed junk into "high".)
    if bool(task.get("needs_verification")):
        reasons.append("low_trust_or_missing_source")
    if confidence < 0.7:
        reasons.append("low_confidence")
    elif confidence < 0.8:
        reasons.append("medium_confidence")

    if status in {"done", "ignored"}:
        score = min(score, 20)
    task["priority_score"] = max(0, int(score))
    task["priority_band"] = _priority_band(task["priority_score"], status=status, has_obligation=has_obligation)
    task["priority_reasons"] = _unique_reasons(reasons)


def _priority_band(score: int, *, status: str, has_obligation: bool = False) -> str:
    if status in {"done", "ignored"}:
        return "closed"
    if has_obligation and score >= 100:
        return "high"
    if score >= 80:
        return "medium"
    return "low"


def _unique_reasons(reasons: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        if not reason or reason in seen:
            continue
        seen.add(reason)
        unique.append(reason)
    return unique


def _max_amount(task: dict[str, Any]) -> float:
    values = task.get("values") if isinstance(task.get("values"), list) else []
    candidates = [str(value) for value in values]
    candidates.append(str(task.get("value") or ""))
    found: list[float] = []
    for candidate in candidates:
        for match in AMOUNT_RE.finditer(candidate):
            try:
                found.append(float(match.group(1).replace(",", "")))
            except ValueError:
                continue
    return max(found, default=0.0)


def _has_action_context(task: dict[str, Any]) -> bool:
    if str(task.get("kind") or "") != "action":
        return False
    text = " ".join(str(task.get(key) or "") for key in ("title", "subject", "evidence", "value")).lower()
    return any(
        term in text
        for term in (
            "submit",
            "schedule",
            "register",
            "apply",
            "verify",
            "reply",
            "contact",
            "cancel",
            "renew",
            "upload",
        )
    )
