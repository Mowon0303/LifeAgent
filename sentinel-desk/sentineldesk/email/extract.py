from __future__ import annotations

import re
from collections.abc import Iterable

from sentineldesk.extract import extract_deadlines, normalize_text

from .models import EmailFact, EmailMessage


AMOUNT_RE = re.compile(
    r"(?<!\w)(?:"
    r"[$€£¥￥]\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?|"
    r"(?:USD|EUR|GBP|CNY|RMB)\s+[0-9][0-9,]*(?:\.[0-9]{1,2})?"
    r")\b",
    re.IGNORECASE,
)
ACTION_RE = re.compile(
    r"\b(?:submit|send|pay|upload|sign|renew|schedule|confirm|respond|complete|"
    r"provide|review|call|email)\b.{0,90}",
    re.IGNORECASE,
)


def find_messages(messages: Iterable[EmailMessage], query: str, *, limit: int = 20) -> list[EmailMessage]:
    terms = [term.lower() for term in re.findall(r"[a-zA-Z0-9_$.-]+", query) if term.strip()]
    all_messages = list(messages)
    matched_threads: set[str] = set()
    scored: list[tuple[int, EmailMessage]] = []
    for message in all_messages:
        haystack = message.searchable_text.lower()
        score = sum(1 for term in terms if term in haystack)
        if not terms or score:
            matched_threads.add(message.thread_id)
            scored.append((score, message))
    if matched_threads:
        already = {message.message_id for _, message in scored}
        for message in all_messages:
            if message.thread_id in matched_threads and message.message_id not in already:
                scored.append((0, message))
    scored.sort(key=lambda item: (item[0], item[1].received_at), reverse=True)
    return [message for _, message in scored[:limit]]


def extract_email_facts(message: EmailMessage) -> list[EmailFact]:
    text = normalize_text(_remove_invisible_number_separators(message.searchable_text))
    facts: list[EmailFact] = []
    for deadline in extract_deadlines(text):
        facts.append(
            EmailFact(
                kind="deadline",
                value=str(deadline["date_text"]),
                source_id=message.source_id,
                source_type=message.source_type,
                trust_label=message.trust_label,
                evidence=str(deadline["context"]),
                confidence=float(deadline["confidence"]),
                received_at=message.received_at,
                metadata=_metadata(message),
            )
        )
    for match in AMOUNT_RE.finditer(text):
        facts.append(
            EmailFact(
                kind="amount",
                value=match.group(0),
                source_id=message.source_id,
                source_type=message.source_type,
                trust_label=message.trust_label,
                evidence=_context(text, match.start(), match.end()),
                confidence=0.78 if _near_risk_word(text, match.start()) else 0.52,
                received_at=message.received_at,
                metadata=_metadata(message),
            )
        )
    for match in ACTION_RE.finditer(text):
        action = normalize_text(match.group(0))
        facts.append(
            EmailFact(
                kind="action",
                value=action[:120],
                source_id=message.source_id,
                source_type=message.source_type,
                trust_label=message.trust_label,
                evidence=_context(text, match.start(), match.end()),
                confidence=0.68,
                received_at=message.received_at,
                metadata=_metadata(message),
            )
        )
    return facts


def _metadata(message: EmailMessage) -> dict[str, str]:
    return {
        "subject": message.subject,
        "sender": message.sender,
        "source_type": message.source_type,
        "trust_label": message.trust_label,
        "attachment_names": ", ".join(message.attachment_names),
    }


def _context(text: str, start: int, end: int, window: int = 90) -> str:
    return text[max(0, start - window) : min(len(text), end + window)]


def _remove_invisible_number_separators(text: str) -> str:
    return re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)


def _near_risk_word(text: str, start: int) -> bool:
    before = text[max(0, start - 80) : start].lower()
    return any(term in before for term in ["due", "balance", "rent", "invoice", "amount", "pay"])
