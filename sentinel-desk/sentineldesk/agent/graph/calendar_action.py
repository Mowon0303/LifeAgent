"""Conversation-driven event creation.

The user explicitly asks to put something on the calendar. The local model
*proposes* the slots (title / date / time); we validate the date and hand back a
proposed event for the user to confirm in chat. Nothing is written here — the
event is created only on the user's confirm click (the red line: no write without
confirmation). The model proposes, deterministic code validates, the human commits.
"""

from __future__ import annotations

import json
import re
import urllib.error
from typing import Any

from sentineldesk.calendar.view import parse_deadline_date
from sentineldesk.relative_dates import resolve_relative_date

from ..schemas import AgentAnswer, Intent

_HM_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")

def _slot_system(today: str) -> str:
    # Built by concatenation, not str.format — the JSON example below contains literal
    # braces that would break a format call.
    return (
        "Extract the single calendar event the user wants to add. Output STRICT JSON "
        "only, no prose, no code fences:\n"
        '{"title": "...", "date": "YYYY-MM-DD", "start_time": "HH:MM" or "", "end_time": "HH:MM" or ""}\n'
        "Today is " + today + "; use it to resolve relative dates (明天, 下周三, tomorrow) "
        "to an absolute YYYY-MM-DD. title is a short noun phrase without date/time words. "
        "If there is no clear event or no resolvable date, output {}."
    )


def _calendar_action_answer(question: str, *, client: Any, today: str) -> AgentAnswer:
    slots = _extract_slots(question, client=client, today=today)
    if slots is None:
        # Can't place it (no model, or no clear event/date) — ask, never guess a date.
        return AgentAnswer(
            intent=Intent.CALENDAR_ACTION,
            answer="好的，我可以帮你加日历。具体是什么事、哪一天（可带时间）？比如「6月20号下午3点 牙医」。",
            confidence="medium",
            tool_calls=("draft_calendar_event",),
        )

    when = slots["date"]
    if slots["start_time"]:
        when += " " + slots["start_time"]
        if slots["end_time"]:
            when += "–" + slots["end_time"]
    return AgentAnswer(
        intent=Intent.CALENDAR_ACTION,
        answer="要把这条加到日历吗：【" + slots["title"] + "】" + when + "（确认后才写）。",
        confidence="medium",
        tool_calls=("draft_calendar_event",),
        requires_confirmation=True,
        metadata={"proposed_event": slots},
    )


def _extract_slots(question: str, *, client: Any, today: str) -> dict | None:
    """Ask the model for the event slots and validate them. Returns a clean
    {title, date, start_time, end_time} dict, or None when there's no model, the
    call fails, or the proposal has no usable title + parseable date."""
    if client is None:
        return None
    # Resolve any relative date deterministically — the model has "today" in the
    # prompt but botches weekday math, so we do it and hand it the answer.
    resolved = resolve_relative_date(question, today)
    system = _slot_system(today)
    if resolved:
        system += '\nThe event date has been resolved to ' + resolved + '; use exactly that as "date".'
    try:
        result = client.chat(system=system, user=question.strip())
    except (urllib.error.URLError, OSError, ValueError, KeyError, AttributeError):
        return None
    data = _parse_json_object(str(getattr(result, "text", "") or ""))
    if not isinstance(data, dict):
        return None
    title = str(data.get("title") or "").strip()
    # A resolved relative date is authoritative (overrides the model's guess);
    # otherwise validate the model's absolute date with the SAME parser the create
    # endpoint uses, so a proposal we accept here can't be rejected at write time.
    date = resolved or parse_deadline_date(str(data.get("date") or "").strip())
    if not title and date:
        # The model sometimes abstains on the title even when we've handed it the date
        # (qwen returns "{}"). We have a valid date, so salvage a title deterministically
        # rather than drop the whole request; the user still confirms it on the card.
        title = _title_from_question(question)
    if not title or not date:
        return None
    return {
        "title": title[:120],
        "date": date,
        "start_time": _valid_hm(str(data.get("start_time") or "")),
        "end_time": _valid_hm(str(data.get("end_time") or "")),
    }


def _parse_json_object(text: str) -> dict | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _valid_hm(value: str) -> str:
    value = value.strip()
    return value if _HM_RE.match(value) else ""


# Tokens to peel off a request to recover the core event title when the model
# abstained — relative-date phrases, time expressions, and lead-in fillers.
_TITLE_STRIP = [
    r"大后天|后天|明天|今天|明儿|今儿",
    r"下(?:个)?(?:周|星期|礼拜)[一二三四五六日天七]",
    r"(?:这|本)(?:周|星期|礼拜)[一二三四五六日天七]",
    r"(?:周|星期|礼拜)[一二三四五六日天七]",
    r"过\s*(?:\d+|[一二两三四五六七八九十]+)\s*天",
    r"(?:\d+|[一二两三四五六七八九十]+)\s*天\s*(?:之?后|後)?",
    r"\d{1,2}[:：]\d{2}",
    r"上午|下午|早上|晚上|中午|凌晨",
    r"[一二三四五六七八九十两\d]+\s*点(?:半|[一二三四五六七八九十\d]+分?)?",
    r"提醒我|提醒|帮我|记一下|记下|添加到日历|加到日历|加入日历|加日历|到日历|日历|安排|预约",
]


def _title_from_question(question: str) -> str:
    text = question
    for pattern in _TITLE_STRIP:
        text = re.sub(pattern, "", text)
    text = re.sub(r"\s+", "", text)
    return text.strip("，。、,.:：；;的和把给与跟为 　")[:120]
