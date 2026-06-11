from __future__ import annotations

from datetime import datetime

from .models import CalendarDraft, DeadlineEvent, normalize_key


def dedupe_events(existing: list[DeadlineEvent], drafts: list[DeadlineEvent]) -> tuple[list[DeadlineEvent], list[DeadlineEvent]]:
    existing_keys = {(event.event_id, normalize_key(event.title), normalize_key(event.date_text)) for event in existing}
    create: list[DeadlineEvent] = []
    update: list[DeadlineEvent] = []
    for draft in drafts:
        key = (draft.event_id, normalize_key(draft.title), normalize_key(draft.date_text))
        if key in existing_keys:
            update.append(draft)
        else:
            create.append(draft)
    return create, update


def plan_calendar_sync(
    draft: CalendarDraft,
    *,
    destination: str = "ics",
    confirmed: bool = False,
) -> dict[str, object]:
    if draft.requires_confirmation and not confirmed:
        return {
            "allowed": False,
            "reason": "calendar_write_requires_confirmation",
            "destination": destination,
            "event_count": len(draft.events),
        }
    return {
        "allowed": True,
        "reason": "confirmed",
        "destination": destination,
        "event_count": len(draft.events),
        "event_ids": [event.event_id for event in draft.events],
    }


def export_ics(events: list[DeadlineEvent], *, calendar_name: str = "LifeAgent Deadlines") -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//LifeAgent//SentinelDesk//EN",
        f"X-WR-CALNAME:{_escape(calendar_name)}",
    ]
    for event in events:
        lines.extend(_event_lines(event))
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _event_lines(event: DeadlineEvent) -> list[str]:
    date_value = _date_to_ics(event.date_text)
    description = "Sources: " + ", ".join(event.source_ids)
    if event.evidence_uri:
        description += "\\nEvidence: " + event.evidence_uri
    return [
        "BEGIN:VEVENT",
        f"UID:{event.event_id}@lifeagent.local",
        f"SUMMARY:{_escape(event.title)}",
        f"DTSTART;VALUE=DATE:{date_value}",
        f"DTEND;VALUE=DATE:{date_value}",
        f"DESCRIPTION:{_escape(description)}",
        f"CATEGORIES:{_escape(event.severity)}",
        "STATUS:TENTATIVE",
        "END:VEVENT",
    ]


def _date_to_ics(date_text: str) -> str:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(date_text, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    compact = "".join(ch for ch in date_text if ch.isdigit())
    if len(compact) == 8 and compact.startswith("20"):
        return compact
    return "19700101"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
