from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any


DATE_RE = re.compile(
    r"\b(?:"
    r"\d{4}-\d{1,2}-\d{1,2}|"
    r"\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r")\b",
    re.IGNORECASE,
)

RELATIVE_DEADLINE_PATTERNS = (
    re.compile(r"\bby the end of the month\b", re.IGNORECASE),
    re.compile(
        r"\bat least\s+\d{1,3}\s+(?:business\s+)?days\s+before\s+the\s+[a-z][a-z -]{0,40}?\b(?:date|end date)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bwithin\s+\d{1,3}\s+(?:business\s+)?days\b", re.IGNORECASE),
    re.compile(r"(?<=\bduring the )\d{1,3}-day grace period\b", re.IGNORECASE),
    re.compile(
        r"\bnext\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        re.IGNORECASE,
    ),
)

RELATIVE_DEADLINE_CUE_RE = re.compile(
    r"\b("
    r"must|need|needs|required|requirement|respond|report|submit|upload|send|pay|payable|"
    r"remove|removed|make changes|cancel|freeze|update|dispute|notice|deadline|due|before|"
    r"grace period|cycle closes|due back"
    r")\b",
    re.IGNORECASE,
)

RELATIVE_DEADLINE_NEGATIVE_RE = re.compile(
    r"\b("
    r"no action (?:is )?(?:needed|required)|not a bill|will be deposited|will be processed|"
    r"company timeline"
    r")\b",
    re.IGNORECASE,
)

STATUS_PATTERNS = [
    ("action_required", r"\b(action required|request for evidence|rfe|missing document|needs your attention|respond by|payment due|rent due|(?<!no )balance due|past due|notice required|notice to vacate required|renewal required)\b"),
    ("interview_requested", r"\b(interview requested|schedule interview|interview invitation|selected an interview slot)\b"),
    ("approved", r"\b(approved|card produced|offer extended|accepted)\b"),
    ("rejected", r"\b(rejected|denied|not selected|will not be moving forward)\b"),
    ("current", r"\b(account current|rent received|paid in full|no balance due|lease active)\b"),
    ("submitted", r"\b(submitted|application received|case received|received your application)\b"),
    ("pending", r"\b(pending|in review|actively reviewing|being reviewed|processing)\b"),
]

SESSION_PATTERNS = [
    ("login_required", r"\b(sign in|log in|login|session expired|password|two-factor|2fa|authentication required)\b"),
    ("bot_blocked", r"\b(captcha|cloudflare|verify you are human|access denied|unusual traffic|blocked)\b"),
    ("server_error", r"\b(temporarily unavailable|internal server error|service unavailable|maintenance)\b"),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def stable_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "section"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "section"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = html.unescape(data).strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        self.parts.append(text)

    @property
    def text(self) -> str:
        return normalize_text("\n".join(self.parts))

    @property
    def title(self) -> str:
        return normalize_text(" ".join(self.title_parts))


@dataclass(frozen=True)
class Extraction:
    title: str
    text: str
    text_hash: str
    health: dict[str, Any]
    status: dict[str, Any]
    deadlines: list[dict[str, Any]]


def visible_text(html_text: str) -> tuple[str, str]:
    parser = VisibleTextParser()
    parser.feed(html_text)
    return parser.title, parser.text


def detect_health(text: str) -> dict[str, Any]:
    normalized = normalize_text(text)
    reasons: list[str] = []
    state = "ok"
    for reason, pattern in SESSION_PATTERNS:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            reasons.append(f"{reason}: {match.group(0)}")
            state = "uncertain"
    if len(normalized) < 80:
        state = "uncertain"
        reasons.append("page_text_too_short")
    return {"state": state, "reasons": reasons, "confidence": 0.95 if state == "ok" else 0.35}


def extract_status(text: str) -> dict[str, Any]:
    normalized = normalize_text(text)
    for status, pattern in STATUS_PATTERNS:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            start, end = match.span()
            evidence = normalized[max(0, start - 70) : min(len(normalized), end + 70)]
            return {"value": status, "evidence": evidence, "confidence": 0.86}
    return {"value": "unknown", "evidence": "", "confidence": 0.2}


def extract_deadlines(text: str) -> list[dict[str, Any]]:
    normalized = normalize_text(text)
    deadlines: list[dict[str, Any]] = []
    for match in DATE_RE.finditer(normalized):
        start, end = match.span()
        context = normalized[max(0, start - 90) : min(len(normalized), end + 90)]
        confidence = _deadline_confidence(context)
        deadlines.append({"date_text": match.group(0), "context": context, "confidence": confidence})
    for match in _relative_deadline_matches(normalized):
        start, end = match.span()
        context = normalized[max(0, start - 90) : min(len(normalized), end + 90)]
        deadlines.append(
            {
                "date_text": match.group(0),
                "context": context,
                "confidence": _deadline_confidence(context, relative=True),
            }
        )
    return deadlines[:10]


def _deadline_confidence(context: str, *, relative: bool = False) -> float:
    high_confidence = re.search(
        r"\b(deadline|due|respond by|before|interview|appointment|expires|must|payable|grace period)\b",
        context,
        re.IGNORECASE,
    )
    if high_confidence:
        return 0.82
    return 0.58 if relative else 0.5


def _relative_deadline_matches(text: str) -> list[re.Match[str]]:
    matches: list[re.Match[str]] = []
    seen_spans: set[tuple[int, int]] = set()
    for pattern in RELATIVE_DEADLINE_PATTERNS:
        for match in pattern.finditer(text):
            span = match.span()
            if span in seen_spans:
                continue
            context = text[max(0, span[0] - 90) : min(len(text), span[1] + 90)]
            if not _is_relative_deadline_context(match.group(0), context):
                continue
            seen_spans.add(span)
            matches.append(match)
    matches.sort(key=lambda item: item.start())
    return matches


def _is_relative_deadline_context(value: str, context: str) -> bool:
    if re.search(r"\bby the end of the month\b", value, re.IGNORECASE):
        return bool(RELATIVE_DEADLINE_CUE_RE.search(context))
    if RELATIVE_DEADLINE_NEGATIVE_RE.search(context):
        return False
    if re.search(r"\bnext\s+\w+\b|\bgrace period\b", value, re.IGNORECASE):
        return bool(RELATIVE_DEADLINE_CUE_RE.search(context))
    return bool(RELATIVE_DEADLINE_CUE_RE.search(context))


def extract_page(html_text: str) -> Extraction:
    title, text = visible_text(html_text)
    return Extraction(
        title=title,
        text=text,
        text_hash=stable_hash(text),
        health=detect_health(text),
        status=extract_status(text),
        deadlines=extract_deadlines(text),
    )
