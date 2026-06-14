"""Answers built directly from extracted email facts: task overview and the
broad "nearest/latest X" query, plus the UI fact-card shape."""

from __future__ import annotations

from sentineldesk.email.extract import extract_email_facts
from sentineldesk.email.models import EmailMessage

from ..schemas import AgentAnswer, Citation, Intent


def _task_overview_answer(messages: list[EmailMessage]) -> AgentAnswer:
    """Answer "what's on my plate" with a short list of upcoming deadlines. Facts
    come through extract_email_facts, so promotional noise is already gated;
    amounts are summarized as a count (ask "how much do I owe" for detail) rather
    than listed, since a raw amount is often a receipt, not an obligation."""
    from sentineldesk.calendar.view import parse_deadline_date
    from sentineldesk.extract import utc_now

    today = utc_now()[:10]
    upcoming: list[tuple[str, object]] = []
    amount_count = 0
    for message in messages:
        for fact in extract_email_facts(message):
            if fact.kind == "deadline":
                iso = parse_deadline_date(fact.value)
                if iso and iso >= today:
                    upcoming.append((iso, fact))
            elif fact.kind == "amount":
                amount_count += 1

    deduped: list[tuple[str, object]] = []
    seen_dates: set[str] = set()
    for iso, fact in sorted(upcoming, key=lambda item: item[0]):
        if iso in seen_dates:
            continue
        seen_dates.add(iso)
        deduped.append((iso, fact))

    if not deduped and not amount_count:
        return AgentAnswer(
            intent=Intent.TASK_OVERVIEW,
            answer="I don't see any upcoming deadlines in your local evidence right now.",
            confidence="medium",
            tool_calls=("search_latest_email",),
        )

    # The per-item detail lives in the cards below, so the answer text stays a
    # short headline — otherwise the model rephrases the whole list into prose
    # that just repeats the cards.
    count = len(deduped)
    answer = (
        f"You have {count} upcoming deadline{'s' if count != 1 else ''}."
        if count
        else "Nothing dated is upcoming."
    )
    if amount_count:
        answer += f" ({amount_count} amount(s) on file — ask \"how much do I owe\" for detail.)"
    # Surface only the nearest deadline as evidence: one card, and the model's
    # grounding scoped to that single fact. Showing every upcoming deadline made a
    # wall of mostly-noise cards, and citing them all let the free rewrite braid one
    # email's amount onto another's date.
    citations = tuple(
        Citation(
            source_id=fact.source_id,
            source_type=fact.source_type,
            evidence=fact.evidence,
            captured_at=fact.received_at,
        )
        for iso, fact in deduped[:1]
    )
    cards = [_fact_card(fact, "deadline") for iso, fact in deduped[:1]]
    return AgentAnswer(
        intent=Intent.TASK_OVERVIEW,
        answer=answer,
        confidence="medium",
        citations=citations,
        tool_calls=("search_latest_email",),
        metadata={"deadline_count": len(deduped), "amount_count": amount_count, "cards": cards},
    )


def _latest_global_answer(
    matches: list,
    *,
    wanted: str,
    intent: Intent,
    tool_calls: list[str],
) -> AgentAnswer:
    """Answer a broad "what's my latest/nearest X" query that spans many
    unrelated emails. The conflict path assumes the facts describe the *same*
    obligation, so it would wrongly report "conflicting evidence" across N
    different deadlines. Pick the single most relevant fact instead — the
    nearest upcoming deadline, or the most recent amount — and say how many
    others exist."""
    chosen = _nearest_deadline_fact(matches) if wanted == "deadline" else _most_recent_fact(matches)
    others = len(matches) - 1
    lead = "Nearest deadline" if wanted == "deadline" else "Latest amount"
    suffix = f" ({others} other {wanted} item{'s' if others != 1 else ''} on file.)" if others > 0 else ""
    return AgentAnswer(
        intent=intent,
        answer=f"{lead}: {chosen.value}.{suffix}",
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
