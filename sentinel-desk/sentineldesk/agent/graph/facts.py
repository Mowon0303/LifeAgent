"""Answers grounded in facts: the task overview (from the user's *accepted*
calendar deadlines) and the broad "nearest/latest X" query over email facts, plus
the UI fact-card shape."""

from __future__ import annotations

import re

from sentineldesk.email.extract_patterns import SETTLEMENT_OBLIGATION

from ..schemas import AgentAnswer, Citation, Intent


_CJK_RE = re.compile(r"[一-鿿]")


def asked_in_chinese(question: str) -> bool:
    """A Chinese question deserves a Chinese answer.

    The product's whole surface is Chinese and the user asks in Chinese, but the
    fact-answer paths returned hardcoded English -- "Conflicting amount evidence
    found: ..." in reply to "这个月要交多少钱？". Switching on the question keeps
    every English-language caller (and test) on exactly the string it had.
    """
    return bool(_CJK_RE.search(question or ""))


def prefer_obligation_amounts(facts: list) -> list:
    """Among amount facts, money actually owed outranks money merely mentioned.

    Settlement is already stamped on every amount fact, but the assistant layer
    was not reading it: a wire the user had themself sent ($11,000.00 plus a
    $45.00 fee, both informational) came back as "conflicting evidence" against
    the one real debt in the mailbox ($31.05). Those three numbers do not
    conflict -- two of them are not obligations at all.
    """
    obligations = [
        fact
        for fact in facts
        if str((getattr(fact, "metadata", None) or {}).get("settlement") or "") == SETTLEMENT_OBLIGATION
    ]
    return obligations or list(facts)


def _task_overview_answer(
    calendar_items: list[dict], *, review_queue_count: int | None = None
) -> AgentAnswer:
    """Answer "what's on my plate" from the deadlines the user has *accepted* into
    the calendar — those are the established facts. Extraction still runs and feeds
    the review queue with candidates, but a candidate only counts here once the user
    confirms it. That's also how promotional/competition noise stays out: you simply
    never accept it, so it never becomes a "fact". When nothing is accepted yet, we
    point at the pending review queue instead of going blank."""
    from sentineldesk.extract import utc_now

    today = utc_now()[:10]
    approved = sorted(
        (
            item
            for item in calendar_items
            if item.get("approval_state") == "approved" and str(item.get("date_key") or "") >= today
        ),
        key=lambda item: str(item.get("date_key") or ""),
    )
    pending_count = sum(
        1
        for item in calendar_items
        if item.get("approval_state") != "approved" and str(item.get("date_key") or "") >= today
    )

    if not approved:
        # Cold start: don't go silent. Send the user to the review card, where the
        # candidates live, so accepting one is one step away.
        #
        # This function only ever sees calendar items -- deadlines. It used to
        # end an empty calendar with "我也没有待复核的候选", which is a claim about
        # the email review queue it never looked at. On a real mailbox that
        # queue held 19 amount/action cards while this sentence said there were
        # none. Scope the claim to what was actually checked, and state the
        # queue only when the caller passed its size.
        if pending_count:
            answer = (
                f"你还没把任何截止加入日历。我找到 {pending_count} 条候选，"
                "在上面的复核卡里逐条确认后就会算进来。"
            )
        elif review_queue_count:
            answer = (
                "你的日历里还没有截止。不过邮件复核队列里有 "
                f"{review_queue_count} 条金额/动作待看——那些不是截止，所以不会进日历。"
            )
        elif review_queue_count == 0:
            answer = "你的日历里还没有截止，邮件复核队列也是空的。"
        else:
            answer = "你的日历里还没有截止。（这里只看日历，邮件复核队列要单独查。）"
        return AgentAnswer(
            intent=Intent.TASK_OVERVIEW,
            answer=answer,
            confidence="medium",
            tool_calls=("search_latest_email",),
            metadata={
                "deadline_count": 0,
                "pending_count": pending_count,
                "review_queue_count": review_queue_count,
                "cards": [],
            },
        )

    # The per-item detail lives in the cards below, so the answer text stays a short
    # headline — otherwise the model just rephrases the whole list back as prose.
    count = len(approved)
    answer = f"You have {count} upcoming deadline{'s' if count != 1 else ''} on your calendar."
    if pending_count:
        answer += f"（另有 {pending_count} 条候选待复核。）"
    # Model grounding (citations) stays scoped to the *nearest* deadline so the prose
    # can't braid one event's detail onto another's date — the same anti-braid scope
    # that matters on the fuzzy RAG path. The cards, by contrast, list every accepted
    # deadline: each is a confirmed, individually grounded fact.
    citations = tuple(
        Citation(
            source_id=(item.get("source_ids") or [""])[0],
            source_type="calendar",
            evidence=str(item.get("date_text") or item.get("title") or ""),
            captured_at="",
        )
        for item in approved[:1]
    )
    cards = [_calendar_card(item) for item in approved]
    return AgentAnswer(
        intent=Intent.TASK_OVERVIEW,
        answer=answer,
        confidence="medium",
        citations=citations,
        tool_calls=("search_latest_email",),
        metadata={"deadline_count": count, "pending_count": pending_count, "cards": cards},
    )


def _calendar_card(item: dict) -> dict:
    source_ids = item.get("source_ids") or []
    return {
        "kind": "deadline",
        "title": str(item.get("title") or ""),
        "date": str(item.get("date_key") or ""),
        "value": str(item.get("date_text") or ""),
        "source_id": str(source_ids[0]) if source_ids else "",
        "event_id": str(item.get("event_id") or ""),
        "evidence": str(item.get("date_text") or ""),
    }


def _latest_global_answer(
    matches: list,
    *,
    wanted: str,
    intent: Intent,
    tool_calls: list[str],
    question: str = "",
) -> AgentAnswer:
    """Answer a broad "what's my latest/nearest X" query that spans many
    unrelated emails. The conflict path assumes the facts describe the *same*
    obligation, so it would wrongly report "conflicting evidence" across N
    different deadlines. Pick the single most relevant fact instead — the
    nearest upcoming deadline, or the most recent amount — and say how many
    others exist."""
    chosen = _nearest_deadline_fact(matches) if wanted == "deadline" else _most_recent_fact(matches)
    others = len(matches) - 1
    if asked_in_chinese(question):
        lead = "最近的截止" if wanted == "deadline" else "最近的金额"
        kind_zh = "截止" if wanted == "deadline" else "金额"
        suffix = f"（另有 {others} 条{kind_zh}记录。）" if others > 0 else ""
        answer_text = f"{lead}：{chosen.value}。{suffix}"
    else:
        lead = "Nearest deadline" if wanted == "deadline" else "Latest amount"
        suffix = f" ({others} other {wanted} item{'s' if others != 1 else ''} on file.)" if others > 0 else ""
        answer_text = f"{lead}: {chosen.value}.{suffix}"
    return AgentAnswer(
        intent=intent,
        answer=answer_text,
        confidence="high" if chosen.confidence >= 0.75 else "medium",
        citations=(
            Citation(
                source_id=chosen.source_id,
                source_type=chosen.source_type,
                evidence=chosen.evidence,
                captured_at=chosen.received_at,
            ),
        ),
        tool_calls=tuple(tool_calls),
        metadata={"scanned": "all_messages", "candidate_count": len(matches), "cards": [_fact_card(chosen, wanted)]},
    )


def _fact_card(fact, kind: str) -> dict:
    """A compact, UI-renderable summary of a fact: the email subject as the
    headline and the resolved date up top, with the sender, receipt date, and
    the evidence snippet revealed when the card is expanded."""
    from sentineldesk.extract import _reference_date

    received = _reference_date(fact.received_at)
    card = {
        "kind": kind,
        "title": str(fact.metadata.get("subject") or fact.value),
        "value": fact.value,
        "date": "",
        "source_id": fact.source_id,
        "sender": str(fact.metadata.get("sender") or ""),
        "received": received.isoformat() if received else str(fact.received_at or "")[:10],
        "evidence": str(fact.evidence or "")[:400],
    }
    if kind == "deadline":
        from sentineldesk.calendar.view import parse_deadline_date

        card["date"] = parse_deadline_date(fact.value) or fact.value
    return card


def _nearest_deadline_fact(matches: list):
    """The soonest upcoming deadline (or, if all are past, the most recent)."""
    from sentineldesk.calendar.view import parse_deadline_date
    from sentineldesk.extract import utc_now

    today = utc_now()[:10]
    dated = [(parse_deadline_date(fact.value), fact) for fact in matches]
    dated = [(iso, fact) for iso, fact in dated if iso]
    if not dated:
        return sorted(matches, key=lambda fact: (fact.confidence, fact.received_at), reverse=True)[0]
    upcoming = sorted(((iso, fact) for iso, fact in dated if iso >= today), key=lambda item: item[0])
    if upcoming:
        return upcoming[0][1]
    return sorted(dated, key=lambda item: item[0])[-1][1]


def _most_recent_fact(matches: list):
    return sorted(matches, key=lambda fact: (fact.received_at, fact.confidence), reverse=True)[0]
