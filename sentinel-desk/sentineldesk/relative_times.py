"""Resolve a Chinese/English clock-time expression (下午4点 / 晚上8点半 / 4pm) to
"HH:MM" (24-hour). The local model botches the AM/PM math the same way it botches
weekday arithmetic — "下午4点" came back as 14:00 in the slot eval — so we do it
deterministically and hand it the answer.

Deliberately conservative: only resolves when there's a clear AM/PM signal (a
Chinese marker like 上午/下午/晚上, an explicit HH:MM, or English am/pm). A bare
"三点" with no marker is genuinely ambiguous (3am vs 3pm), so we return "" and let
the model's value stand rather than guess.
"""

from __future__ import annotations

import re

from .relative_dates import _to_int

_HM_RE = re.compile(r"\b([01]?\d|2[0-3])[:：]([0-5]\d)\b")
_EN_RE = re.compile(r"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*([ap])\.?m\.?\b", re.IGNORECASE)

_MARKER = r"(上午|早上|早晨|清晨|凌晨|半夜|下午|晚上|傍晚|夜里|夜晚|中午|正午)"
_HOUR = r"(\d{1,2}|[零一二两三四五六七八九十]{1,3})"
_MINUTE = r"(半|(?:\d{1,2}|[零一二三四五六七八九十]{1,3})\s*分)"
_CN_RE = re.compile(_MARKER + r"\s*(?:" + _HOUR + r"\s*[点點时時])?\s*" + _MINUTE + r"?")
# A range like "下午2点到3点" — the end borrows the start's AM/PM marker when it lacks one.
_ONE = _MARKER + r"?\s*" + _HOUR + r"\s*[点點时時]\s*" + _MINUTE + r"?"
_CN_RANGE_RE = re.compile(_ONE + r"\s*(?:到|至|~|～|–|—|-)\s*" + _ONE)

_PM_MARKERS = {"下午", "傍晚"}
_EVENING_MARKERS = {"晚上", "夜里", "夜晚"}
_AM_MARKERS = {"上午", "早上", "早晨", "清晨", "凌晨", "半夜"}
_NOON_MARKERS = {"中午", "正午"}


def resolve_clock_time(text: str) -> str:
    """Absolute "HH:MM" for a clear time expression in ``text``, or "" if none."""
    # English am/pm is checked before bare HH:MM, else "11:30pm" matches "11:30".
    match = _EN_RE.search(text)
    if match:
        hour, minute, ap = int(match.group(1)), int(match.group(2) or 0), match.group(3).lower()
        if ap == "p" and hour != 12:
            hour += 12
        if ap == "a" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"

    match = _HM_RE.search(text)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"

    match = _CN_RE.search(text)
    if match:
        return _build_cn_time(match.group(1), match.group(2), match.group(3))
    return ""


def resolve_clock_range(text: str) -> tuple[str, str]:
    """(start, end) for a time range like "下午2点到3点" (→ 14:00, 15:00); ("HH:MM", "")
    for a single time; ("", "") when there's no clear AM/PM signal."""
    match = _CN_RANGE_RE.search(text)
    if match:
        m1, h1, min1, m2, h2, min2 = match.groups()
        start = _build_cn_time(m1 or m2, h1, min1)   # borrow a marker if one side lacks it
        end = _build_cn_time(m2 or m1, h2, min2)
        if start and end:
            return start, end
    return resolve_clock_time(text), ""


def _build_cn_time(marker: str | None, hour_token: str | None, minute_token: str | None) -> str:
    if not marker:
        return ""  # no AM/PM signal -> ambiguous, leave it to the model
    minute = _minutes(minute_token)
    if hour_token is None:
        return "12:00" if marker in _NOON_MARKERS else ""
    hour = _to_int(hour_token)
    if hour is None or not 0 <= hour <= 23:
        return ""
    hour = _apply_marker(marker, hour)
    return f"{hour:02d}:{minute:02d}" if 0 <= hour <= 23 else ""


def _apply_marker(marker: str, hour: int) -> int:
    if marker in _PM_MARKERS:
        return hour + 12 if 1 <= hour <= 11 else hour
    if marker in _EVENING_MARKERS:
        if 1 <= hour <= 11:
            return hour + 12
        return 0 if hour == 12 else hour  # 晚上12点 = midnight
    if marker in _AM_MARKERS:
        if hour == 12:
            return 0 if marker in {"凌晨", "半夜"} else 12
        return hour
    if marker in _NOON_MARKERS:  # 中午1点 = 13:00, 中午12点 = 12:00
        return hour + 12 if 1 <= hour <= 5 else (12 if hour == 12 else hour)
    return hour


def _minutes(token: str | None) -> int:
    if not token:
        return 0
    if "半" in token:
        return 30
    match = re.search(r"(\d{1,2}|[零一二三四五六七八九十]{1,3})", token)
    if match:
        value = _to_int(match.group(1))
        if value is not None and 0 <= value <= 59:
            return value
    return 0
