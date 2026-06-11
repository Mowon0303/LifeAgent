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
BASE_ACTION_VERBS = (
    "submit",
    "send",
    "pay",
    "upload",
    "sign",
    "renew",
    "schedule",
    "confirm",
    "respond",
    "complete",
    "provide",
    "review",
    "call",
    "email",
)
EXPANDED_ACTION_VERBS = (
    "contact",
    "register",
    "apply",
    "dispute",
    "redeem",
    "update",
    "cancel",
    "verify",
    "reply",
    "bring",
    "report",
    "check",
    "add",
    "print",
    "enroll",
    "contest",
)
ACTION_VERBS = BASE_ACTION_VERBS + EXPANDED_ACTION_VERBS
ACTION_RE = re.compile(
    r"\b(?P<verb>" + "|".join(ACTION_VERBS) + r")\b.{0,90}",
    re.IGNORECASE,
)
ACTION_CUE_WORDS = {
    "and",
    "after",
    "before",
    "by",
    "can",
    "cannot",
    "could",
    "if",
    "may",
    "must",
    "or",
    "please",
    "should",
    "then",
    "to",
    "unless",
    "will",
    "would",
}
CONTEXT_SENSITIVE_ACTION_VERBS = {"check", "report", "update"}


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
        verb = match.group("verb").lower()
        action = normalize_text(match.group(0))
        if not _action_context_allowed(text, match.start(), verb, action):
            continue
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


def _action_context_allowed(text: str, start: int, verb: str, action: str) -> bool:
    lowered = action.lower()
    if (
        verb == "contact"
        and "support" in lowered
        and "if you did not" in text[max(0, start - 90) : start].lower()
    ):
        return False
    if verb == "reply" and _looks_like_email_local_part(text, start, verb):
        return False
    if verb == "apply" and re.search(
        r"\b(?:charges|fees|rates|conditions|terms) may\s+$",
        text[max(0, start - 40) : start].lower(),
    ):
        return False
    if verb == "apply" and _previous_word(text, start) in {
        "charges",
        "conditions",
        "fees",
        "rates",
        "terms",
    }:
        return False
    if verb == "update" and re.search(r"\bupdate from (?:your )?device'?s app store\b", lowered):
        return False
    if verb not in CONTEXT_SENSITIVE_ACTION_VERBS:
        return True
    if _starts_action_clause(text, start):
        return True
    previous = _previous_word(text, start)
    return previous in ACTION_CUE_WORDS


def _starts_action_clause(text: str, start: int) -> bool:
    before = text[:start].rstrip(" \t\r")
    if not before:
        return True
    return before[-1] in ".!?:;,\n"


def _previous_word(text: str, start: int) -> str:
    match = re.search(r"([A-Za-z]+)$", text[:start].rstrip())
    return match.group(1).lower() if match else ""


def _looks_like_email_local_part(text: str, start: int, verb: str) -> bool:
    after = start + len(verb)
    previous = text[start - 1] if start > 0 else ""
    next_char = text[after] if after < len(text) else ""
    return previous in "-_." or next_char in "@_.-"
