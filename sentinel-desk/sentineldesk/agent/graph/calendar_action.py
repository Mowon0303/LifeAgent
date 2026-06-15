"""Conversation-driven calendar actions: create / edit / delete an event.

The user asks in natural language; the local model *proposes* (the new event's
slots, or which existing event they mean + the change). Deterministic code
validates, and nothing is written until the user confirms in chat (the red line:
no write without confirmation).

For edit/delete the hard part is reference resolution — "把牙医那条改到周四" — so we
hand the model the (small) list of existing events and it ranks the targets; we
surface the top pick to confirm, with the top-3 as a "not that one?" fallback.
"""

from __future__ import annotations

import json
import re
import urllib.error
from typing import Any

from sentineldesk.calendar.view import parse_deadline_date
from sentineldesk.relative_dates import resolve_relative_date
from sentineldesk.relative_times import resolve_clock_time

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


_DELETE_RE = re.compile(r"删除|删掉|删|取消|去掉|移除|不要了|remove|delete|cancel", re.IGNORECASE)
_EDIT_RE = re.compile(r"改到|改成|改为|改一?下|修改|挪到|挪一?下|换到|调整|推迟|提前|顺延|move|reschedule|change|update", re.IGNORECASE)


def _classify_calendar_action(question: str) -> str:
    if _DELETE_RE.search(question):
        return "delete"
    if _EDIT_RE.search(question):
        return "edit"
    return "create"


_EMAIL_REF_RE = re.compile(r"邮件|这封|那封|那个邮件|来信|信里|邮箱里|email", re.IGNORECASE)


def _calendar_action_answer(
    question: str,
    *,
    client: Any,
    today: str,
    events: list[dict] | None = None,
    registry: Any = None,
    messages: list | None = None,
) -> AgentAnswer:
    action = _classify_calendar_action(question)
    if action in ("edit", "delete"):
        return _edit_delete_answer(question, action, list(events or []), client=client, today=today)
    return _create_answer(question, client=client, today=today, registry=registry, messages=messages)


def _create_answer(
    question: str, *, client: Any, today: str, registry: Any = None, messages: list | None = None
) -> AgentAnswer:
    # "把 USCIS 那封的截止加日历" — the date lives in an email, not the message. Pull it
    # from the referenced mail via RAG instead of asking the model for a date.
    if _EMAIL_REF_RE.search(question):
        return _email_event_answer(question, registry=registry, messages=messages or [], today=today)
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


_QUERY_STRIP = re.compile(
    r"把|帮我|请|麻烦|邮件|这封|那封|那个|来信|信里|邮箱里|email|的|截止|到期|最后期限|deadline|due|"
    r"加到日历|加入日历|加日历|到日历|添加|日历|事项|提醒我?",
    re.IGNORECASE,
)


def _email_event_answer(question: str, *, registry: Any, messages: list, today: str) -> AgentAnswer:
    """Find the email the user referenced, pull its deadline, and propose a calendar
    event from it. Fully deterministic given the email — the date is the email's, not a
    model guess. Reuses the create confirm card.

    "那封 Tripalink" is genuinely ambiguous — the email *titled* Tripalink, or one *from*
    Tripalink — so when several emails match, we carry the alternatives and let the card
    offer a "不是这个" picker instead of silently guessing."""
    message, subject, source_id, deadline, candidates = _resolve_email_reference(
        question, registry=registry, messages=messages, today=today
    )
    if message is None and not subject:
        return _calendar_reply("没找到相关邮件。你指哪封？说个关键词（发件人或主题），比如「USCIS」。")
    if not deadline:
        return _calendar_reply("「" + (subject or "那封邮件") + "」里我没找到明确的截止日期。你想手动给个日期吗？")
    slots: dict[str, Any] = {"title": _clean_subject(subject) or "邮件事项", "date": deadline, "start_time": "", "end_time": ""}
    # Only offer the picker when there's a real choice to make — a lone match needs none.
    if len(candidates) > 1:
        slots["candidates"] = candidates
    return AgentAnswer(
        intent=Intent.CALENDAR_ACTION,
        answer="要把「" + (subject or "那封邮件") + "」的截止 " + deadline + " 加到日历吗？（确认后才写）",
        confidence="medium",
        tool_calls=("draft_calendar_event",),
        requires_confirmation=True,
        metadata={"proposed_event": slots, "source_email": source_id},
    )


def _resolve_email_reference(question: str, *, registry: Any, messages: list, today: str):
    """Return (message, subject, source_id, deadline, candidates) for the referenced email.

    A named reference ("Tripalink", "USCIS") matches the subject/sender deterministically
    — far more reliable than semantic RAG, which ranks bare keywords poorly. RAG is the
    fallback when nothing matches by name.

    ``candidates`` is the ranked (best-first) list of *deadline-bearing* name-matches as
    picker briefs. An email without a deadline can't become a calendar event, so it's not
    a viable alternative; the top-1 we propose is always the highest-scored one that does
    have a date."""
    query = _email_search_query(question)
    tokens = [token.lower() for token in re.split(r"[\s，,、]+", query) if len(token) >= 2]
    matches: list[tuple] = []  # (score, has_deadline, message, deadline)
    for message in messages:
        subject = str(getattr(message, "subject", "") or "").lower()
        sender = str(getattr(message, "sender", "") or "").lower()
        subject_hits = sum(1 for token in tokens if token in subject)
        sender_hits = sum(1 for token in tokens if token in sender)
        if not subject_hits and not sender_hits:
            continue
        deadline = _nearest_deadline(message, today)
        # A subject match is a stronger reference than a sender-only match ("the
        # Tripalink one" means the email titled Tripalink, not every email from them).
        score = subject_hits * 2 + sender_hits
        matches.append((score, 1 if deadline else 0, message, deadline))
    if matches:
        # Rank best-first; the sort is stable, so equal scores keep their listed order.
        matches.sort(key=lambda match: match[:2], reverse=True)
        viable = [match for match in matches if match[3]]
        if viable:
            top = viable[0][2]
            candidates = [_email_brief(match[2], match[3]) for match in viable][:_MAX_EMAIL_CANDIDATES]
            return top, _subject_of(top), _source_of(top), viable[0][3], candidates
        # Matched by name, but nothing has a usable deadline — surface the best match so
        # the "no deadline" reply can name it, with no alternatives to pick from.
        top = matches[0][2]
        return top, _subject_of(top), _source_of(top), "", []

    document = _top_email_match(query, registry)
    if document is None:
        return None, "", "", "", []
    source_id = str(document.get("source_id") or "")
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    message = next((m for m in messages if str(getattr(m, "source_id", "") or "") == source_id), None)
    subject = str(metadata.get("subject") or document.get("title") or (getattr(message, "subject", "") if message else "")).strip()
    deadline = (
        _nearest_deadline(message, today)
        if message is not None
        else _deadline_from_text(str(document.get("text") or ""), today)
    )
    # RAG returns a single top doc, so there's never more than one alternative here.
    return message, subject, source_id, deadline, []


_MAX_EMAIL_CANDIDATES = 5


def _email_brief(message: Any, deadline: str) -> dict:
    """A picker-ready summary of a matched email — enough to tell a subject match from a
    sender match ("titled Tripalink" vs "from Tripalink") and to re-fill the create card."""
    subject = _subject_of(message)
    return {
        "title": _clean_subject(subject) or "邮件事项",
        "date": deadline,
        "start_time": "",
        "end_time": "",
        "subject": subject,
        "sender": _sender_of(message),
        "source_email": _source_of(message),
    }


def _subject_of(message: Any) -> str:
    return str(getattr(message, "subject", "") or "")


def _sender_of(message: Any) -> str:
    return str(getattr(message, "sender", "") or "")


def _source_of(message: Any) -> str:
    return str(getattr(message, "source_id", "") or "")


def _email_search_query(question: str) -> str:
    cleaned = re.sub(r"\s+", " ", _QUERY_STRIP.sub(" ", question)).strip()
    return cleaned or question


def _top_email_match(query: str, registry: Any) -> dict | None:
    if registry is None:
        return None
    try:
        spec = registry.assert_can_call("search_email_rag")
    except (KeyError, PermissionError):
        return None
    if getattr(spec, "handler", None) is None:
        return None
    try:
        result = registry.call("search_email_rag", query=query, limit=4)
    except Exception:
        return None
    documents = list(result.get("documents") or []) if isinstance(result, dict) else []
    return documents[0] if documents else None


def _nearest_deadline(message: Any, today: str) -> str:
    from sentineldesk.email.extract import extract_email_facts

    isos = [
        parse_deadline_date(fact.value)
        for fact in extract_email_facts(message)
        if fact.kind == "deadline" and parse_deadline_date(fact.value)
    ]
    return _pick_deadline(isos, today)


def _deadline_from_text(text: str, today: str) -> str:
    from sentineldesk.extract import extract_deadlines

    isos = [parse_deadline_date(str(d.get("date_text") or "")) for d in extract_deadlines(text)]
    return _pick_deadline([iso for iso in isos if iso], today)


def _pick_deadline(isos: list[str], today: str) -> str:
    if not isos:
        return ""
    upcoming = sorted(iso for iso in isos if iso >= today)
    return upcoming[0] if upcoming else sorted(isos)[0]


def _clean_subject(subject: str) -> str:
    return re.sub(r"^(?:re|fwd|fw)\s*[:：]\s*", "", subject, flags=re.IGNORECASE).strip()[:120]


def _edit_delete_answer(
    question: str, action: str, events: list[dict], *, client: Any, today: str
) -> AgentAnswer:
    verb = "删除" if action == "delete" else "修改"
    pool = [event for event in events if event.get("event_id")]
    if not pool:
        return _calendar_reply("你的日历里还没有可以" + verb + "的事件。")
    if client is None:
        return _calendar_reply("我可以帮你" + verb + "日历事件，但得靠本地模型理解你指的是哪一条。")

    target_indexes, changes = _resolve_targets(question, action, pool, today=today, client=client)
    ranked = [pool[index] for index in target_indexes]
    if not ranked:
        return _calendar_reply("没找到你说的那条。你日历里有：" + _brief_list(pool) + "，想" + verb + "哪个？")

    # The model's picks first (best match on top), then the rest of the calendar as
    # alternatives — so "不是这个" always has somewhere to go even when the model
    # returned a single confident pick for an ambiguous reference.
    seen = {event["event_id"] for event in ranked}
    candidates = (ranked + [event for event in pool if event.get("event_id") not in seen])[:6]

    if action == "edit":
        changes = _normalize_changes(question, changes, today)
        if not changes:
            return _calendar_reply("想把【" + _label(candidates[0]) + "】改成什么？（日期/时间/标题）")

    return AgentAnswer(
        intent=Intent.CALENDAR_ACTION,
        answer=_change_sentence(action, candidates[0], changes),
        confidence="medium",
        tool_calls=("draft_calendar_event",),
        requires_confirmation=True,
        metadata={
            "proposed_change": {
                "action": action,
                "target": _event_brief(candidates[0]),
                "changes": changes if action == "edit" else {},
                "candidates": [_event_brief(event) for event in candidates],
            }
        },
    )


def _resolve_targets(
    question: str, action: str, events: list[dict], *, today: str, client: Any
) -> tuple[list[int], dict]:
    """Ask the model which listed event(s) the user means, ranked best-first, plus
    any field changes. Returns 0-based indexes into ``events`` and a changes dict."""
    listing = "\n".join(
        str(index + 1) + ". " + str(event.get("title") or "") + " | " + _label_date(event)
        + (" " + str(event.get("start_time")) if event.get("start_time") else "")
        for index, event in enumerate(events)
    )
    system = (
        "The user wants to " + action + " one of these calendar events. Choose which "
        "event(s) they mean, MOST LIKELY FIRST, by line number. Output STRICT JSON only, "
        "no prose:\n"
        '{"targets": [1, 2], "changes": {"date": "YYYY-MM-DD or empty", "start_time": "HH:MM or empty", "end_time": "", "title": ""}}\n'
        "targets: the line numbers, ranked by likelihood (best first). For a delete, set "
        'changes to {}. For an edit, fill ONLY the fields that change. Today is ' + today + ".\n"
        "Events:\n" + listing
    )
    try:
        result = client.chat(system=system, user=question.strip())
    except (urllib.error.URLError, OSError, ValueError, KeyError, AttributeError):
        return [], {}
    data = _parse_json_object(str(getattr(result, "text", "") or ""))
    if not isinstance(data, dict):
        return [], {}
    indexes: list[int] = []
    raw_targets = data.get("targets")
    for value in raw_targets if isinstance(raw_targets, list) else []:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= len(events) and (number - 1) not in indexes:
            indexes.append(number - 1)
    changes = data.get("changes") if isinstance(data.get("changes"), dict) else {}
    return indexes, changes


def _normalize_changes(question: str, changes: dict, today: str) -> dict:
    out: dict[str, str] = {}
    resolved = resolve_relative_date(question, today)
    date = resolved or parse_deadline_date(str(changes.get("date") or "").strip())
    if date:
        out["date"] = date
    start = resolve_clock_time(question) or _valid_hm(str(changes.get("start_time") or ""))
    if start:
        out["start_time"] = start
    end = _valid_hm(str(changes.get("end_time") or ""))
    if end:
        out["end_time"] = end
    title = str(changes.get("title") or "").strip()
    if title:
        out["title"] = title[:120]
    return out


def _change_sentence(action: str, target: dict, changes: dict) -> str:
    label = "【" + _label(target) + "】"
    if action == "delete":
        return "要从日历删掉" + label + "吗？（确认后才删）"
    parts: list[str] = []
    if "date" in changes:
        parts.append("日期→" + changes["date"])
    if "start_time" in changes:
        parts.append("时间→" + changes["start_time"] + ("–" + changes["end_time"] if "end_time" in changes else ""))
    if "title" in changes:
        parts.append("标题→" + changes["title"])
    return "要把" + label + "改成（" + "，".join(parts) + "）吗？（确认后才改）"


def _event_brief(event: dict) -> dict:
    return {
        "event_id": str(event.get("event_id") or ""),
        "title": str(event.get("title") or ""),
        "date": _label_date(event),
        "start_time": str(event.get("start_time") or ""),
        "end_time": str(event.get("end_time") or ""),
    }


def _label_date(event: dict) -> str:
    return str(event.get("date_key") or event.get("date") or "")


def _label(event: dict) -> str:
    title = str(event.get("title") or "这条")
    date = _label_date(event)
    return (title + " " + date).strip()


def _brief_list(events: list[dict]) -> str:
    return "、".join("「" + _label(event) + "」" for event in events[:6])


def _calendar_reply(text: str) -> AgentAnswer:
    return AgentAnswer(
        intent=Intent.CALENDAR_ACTION,
        answer=text,
        confidence="medium",
        tool_calls=("draft_calendar_event",),
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
        # A marked time ("下午4点") is resolved deterministically and overrides the
        # model's guess — same reasoning as the date; the model botches AM/PM.
        "start_time": resolve_clock_time(question) or _valid_hm(str(data.get("start_time") or "")),
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
