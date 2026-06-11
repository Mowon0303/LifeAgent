from __future__ import annotations

from sentineldesk.email.models import EmailFact

from .models import CalendarDraft, DeadlineEvent


def draft_events_from_facts(facts: list[EmailFact], *, evidence_uri: str = "") -> CalendarDraft:
    events: list[DeadlineEvent] = []
    for fact in facts:
        if fact.kind != "deadline":
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
