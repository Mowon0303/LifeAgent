"""Resolve relative date phrases (明天 / 三天后 / 下周三 / next Friday) to an
absolute ISO date, anchored on a given ``today``.

The local model reliably reads "today" from a prompt but botches the weekday/date
arithmetic (the agent eval measured this — see docs/AGENT_EVAL.md). So we do the
arithmetic deterministically and hand it the answer. Returns "" when the text holds
no recognizable relative phrase, leaving absolute dates to the normal parser.
"""

from __future__ import annotations

import datetime as dt
import re

# Monday=0 … Sunday=6, matching date.weekday().
_CN_WEEKDAY = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6, "七": 6}
_EN_WEEKDAY = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def resolve_relative_date(text: str, today_iso: str) -> str:
    """Absolute ISO date for a relative phrase in ``text``, or "" if none."""
    try:
        today = dt.date.fromisoformat(str(today_iso)[:10])
    except (ValueError, TypeError):
        return ""
    lowered = text.lower()

    # ---- fixed day offsets (check 大后天 before 后天 before 明天) ----
    if "大后天" in text:
        return _shift(today, 3)
    if "后天" in text or "the day after tomorrow" in lowered:
        return _shift(today, 2)
    if "明天" in text or "明儿" in text or "tomorrow" in lowered:
        return _shift(today, 1)
    if "今天" in text or "今儿" in text or "today" in lowered:
        return _shift(today, 0)

    # ---- N days from now: 三天后 / 3天后 / 过五天 / in 3 days ----
    offset = _days_offset(text, lowered)
    if offset is not None:
        return _shift(today, offset)

    # ---- next week's weekday: 下周三 / 下星期一 / next Friday ----
    match = re.search(r"下(?:个)?(?:周|星期|礼拜)\s*([一二三四五六日天七])", text)
    if match:
        return _weekday_in_week(today, _CN_WEEKDAY[match.group(1)], weeks_ahead=1)
    match = re.search(r"next\s+(" + "|".join(_EN_WEEKDAY) + r")", lowered)
    if match:
        return _weekday_in_week(today, _EN_WEEKDAY[match.group(1)], weeks_ahead=1)

    # ---- this week's weekday: 这周五 / 本周三 ----
    match = re.search(r"(?:这|本)(?:周|星期|礼拜)\s*([一二三四五六日天七])", text)
    if match:
        return _weekday_in_week(today, _CN_WEEKDAY[match.group(1)], weeks_ahead=0)

    # ---- bare weekday -> the upcoming one: 周三 / 星期五 / on Friday ----
    match = re.search(r"(?:周|星期|礼拜)\s*([一二三四五六日天七])", text)
    if match:
        return _upcoming_weekday(today, _CN_WEEKDAY[match.group(1)])
    match = re.search(r"\b(" + "|".join(_EN_WEEKDAY) + r")\b", lowered)
    if match:
        return _upcoming_weekday(today, _EN_WEEKDAY[match.group(1)])

    return ""


def _shift(today: dt.date, days: int) -> str:
    return (today + dt.timedelta(days=days)).isoformat()


def _days_offset(text: str, lowered: str) -> int | None:
    # 过N天 (after N days) or N天后 — both mean "N days from now".
    match = re.search(r"过\s*(\d+|[一二两三四五六七八九十]+)\s*天", text)
    if match is None:
        match = re.search(r"(\d+|[一二两三四五六七八九十]+)\s*天\s*(?:之?后|後)", text)
    if match:
        value = _to_int(match.group(1))
        if value is not None:
            return value
    match = re.search(r"in\s+(\d+)\s+days?", lowered) or re.search(r"(\d+)\s+days?\s+(?:from now|later)", lowered)
    if match:
        return int(match.group(1))
    return None


def _weekday_in_week(today: dt.date, weekday: int, *, weeks_ahead: int) -> str:
    monday = today - dt.timedelta(days=today.weekday())
    target = monday + dt.timedelta(weeks=weeks_ahead, days=weekday)
    return target.isoformat()


def _upcoming_weekday(today: dt.date, weekday: int) -> str:
    ahead = (weekday - today.weekday()) % 7
    ahead = ahead or 7  # "周三" said on a Wednesday means the next one, not today
    return (today + dt.timedelta(days=ahead)).isoformat()


def _to_int(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    if token == "十":
        return 10
    if "十" in token:
        tens, _, ones = token.partition("十")
        tens_value = _CN_DIGIT.get(tens, 1) if tens else 1
        ones_value = _CN_DIGIT.get(ones, 0) if ones else 0
        return tens_value * 10 + ones_value
    total = 0
    for char in token:
        if char not in _CN_DIGIT:
            return None
        total = total * 10 + _CN_DIGIT[char]
    return total or None
