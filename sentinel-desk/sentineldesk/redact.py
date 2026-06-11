from __future__ import annotations

import re


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)")
URL_RE = re.compile(r"(?:https?|file)://[^\s)>\"]+")
PATH_RE = re.compile(r"(?<![A-Za-z0-9_])/(?:Users|private|tmp|var|Volumes)/[^\s)>\"]+")
ID_RE = re.compile(r"\b(?:A-?\d{8,12}|\d{3}-\d{2}-\d{4})\b")


def redact(text: str) -> str:
    value = EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    value = PHONE_RE.sub("[REDACTED_PHONE]", value)
    value = ID_RE.sub("[REDACTED_ID]", value)
    value = URL_RE.sub("[REDACTED_URL]", value)
    value = PATH_RE.sub("[REDACTED_PATH]", value)
    return value
