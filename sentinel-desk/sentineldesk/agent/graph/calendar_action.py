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
    try:
        result = client.chat(system=_slot_system(today), user=question.strip())
    except (urllib.error.URLError, OSError, ValueError, KeyError, AttributeError):
        return None
    data = _parse_json_object(str(getattr(result, "text", "") or ""))
    if not isinstance(data, dict):
        return None
    title = str(data.get("title") or "").strip()
    # Validate the date with the SAME parser the create endpoint uses, so a proposal
    # we accept here can't be rejected at write time.
    date = parse_deadline_date(str(data.get("date") or "").strip())
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
