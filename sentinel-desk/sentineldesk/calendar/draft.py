from __future__ import annotations

from sentineldesk.email.models import EmailFact
from sentineldesk.extract import resolve_relative_deadline

from .models import CalendarDraft, DeadlineEvent
from .view import parse_deadline_date


def draft_events_from_facts(facts: list[EmailFact], *, evidence_uri: str = "") -> CalendarDraft:
    events: list[DeadlineEvent] = []
    for fact in facts:
        if fact.kind != "deadline":
            continue
        date_text = fact.value
        estimated = False
        if not parse_deadline_date(date_text):
            # A relative phrase ("respond within 10 days") has no calendar date on
            # its own. Compute one from the email's receipt date when it is
            # anchored to "now"; anything anchored to an external event ("within
            # 30 days of your program end date") stays a date-less review task and
            # is never offered as a calendar event.
            resolved = resolve_relative_deadline(date_text, fact.received_at, context=fact.evidence)
            if not resolved:
                continue
            date_text = resolved
            estimated = True
        subject = _calendar_title(fact.metadata.get("subject", ""))
        # An estimated date is only a suggestion — keep it medium severity so the
        # draft reads as uncertain and the user confirms before it is trusted.
        confidence = min(fact.confidence, 0.65) if estimated else fact.confidence
        events.append(
            DeadlineEvent(
                title=subject,
                date_text=date_text,
                source_ids=(fact.source_id,),
                severity="critical" if confidence >= 0.8 else "medium",
                confidence=confidence,
                evidence_uri=evidence_uri,
            )
        )
    return CalendarDraft(events=tuple(events))


def _calendar_title(subject: object) -> str:
    title = " ".join(str(subject or "").split())
    return title or "Life admin deadline"
