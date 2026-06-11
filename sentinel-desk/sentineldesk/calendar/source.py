from __future__ import annotations

from .models import DeadlineEvent, ReminderRule


def events_from_calendar_rows(rows: list[dict[str, object]], *, event_id: str | None = None) -> list[DeadlineEvent]:
    events: list[DeadlineEvent] = []
    for row in rows:
        if event_id and row.get("event_id") != event_id:
            continue
        reminders = tuple(
            ReminderRule(days_before=int(item.get("days_before", 0)), method=str(item.get("method", "display")))
            for item in row.get("reminders", [])
            if isinstance(item, dict)
        )
        events.append(
            DeadlineEvent(
                title=str(row.get("title") or ""),
                date_text=str(row.get("date_text") or ""),
                source_ids=tuple(str(item) for item in row.get("source_ids", [])),
                severity=str(row.get("severity") or "medium"),
                confidence=float(row.get("confidence") or 0.0),
                status=str(row.get("status") or "draft"),
                evidence_uri=str(row.get("evidence_uri") or ""),
                reminders=reminders or (ReminderRule(14), ReminderRule(7), ReminderRule(1)),
                event_id=str(row.get("event_id") or ""),
            )
        )
    return events
