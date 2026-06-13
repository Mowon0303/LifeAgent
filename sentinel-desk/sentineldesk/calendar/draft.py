from __future__ import annotations

from sentineldesk.email.models import EmailFact

from .models import CalendarDraft, DeadlineEvent
from .view import parse_deadline_date


def draft_events_from_facts(facts: list[EmailFact], *, evidence_uri: str = "") -> CalendarDraft:
    events: list[DeadlineEvent] = []
    for fact in facts:
        if fact.kind != "deadline":
            continue
        # A deadline with no resolvable calendar date (e.g. a relative phrase like
        # "within 30 days") is not a calendar event — it stays an email fact / review
        # task instead, so we never offer to add a dateless item to the calendar.
        if not parse_deadline_date(fact.value):
            continue
        subject = fact.metadata.get("subject", "Life admin deadline")
        events.append(
            DeadlineEvent(
                title=f"Deadline: {subject}",
                date_text=fact.value,
                source_ids=(fact.source_id,),
                severity="critical" if fact.confidence >= 0.8 else "medium",
                confidence=fact.confidence,
                evidence_uri=evidence_uri,
            )
        )
    return CalendarDraft(events=tuple(events))
