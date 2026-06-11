from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Protocol

from sentineldesk import db
from sentineldesk.config import Paths
from sentineldesk.extract import utc_now

from .models import CalendarDraft, DeadlineEvent
from .sync import export_ics, plan_calendar_sync


@dataclass(frozen=True)
class CalendarSyncResult:
    allowed: bool
    destination: str
    reason: str
    event_ids: tuple[str, ...] = ()
    external_ids: tuple[str, ...] = ()
    created_external_ids: tuple[str, ...] = ()
    updated_external_ids: tuple[str, ...] = ()
    output_path: str = ""


class CalendarAdapter(Protocol):
    destination: str
    side_effect: str

    def sync(self, events: tuple[DeadlineEvent, ...]) -> CalendarSyncResult:
        ...


class IcsFileCalendarAdapter:
    destination = "ics_file"
    side_effect = "local_file_write"

    def __init__(self, output_path: str | Path) -> None:
        self.output_path = Path(output_path)

    def sync(self, events: tuple[DeadlineEvent, ...]) -> CalendarSyncResult:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(export_ics(list(events)), encoding="utf-8")
        return CalendarSyncResult(
            allowed=True,
            destination=self.destination,
            reason="confirmed",
            event_ids=tuple(event.event_id for event in events),
            external_ids=tuple(f"ics:{event.event_id}" for event in events),
            created_external_ids=tuple(f"ics:{event.event_id}" for event in events),
            output_path=str(self.output_path),
        )


class GoogleCalendarAdapter:
    destination = "google_calendar"
    side_effect = "external_calendar_write"

    def __init__(self, client: object | None = None, calendar_id: str = "primary") -> None:
        self.client = client
        self.calendar_id = calendar_id

    def sync(self, events: tuple[DeadlineEvent, ...]) -> CalendarSyncResult:
        if self.client is None:
            raise RuntimeError("Google Calendar adapter requires an authenticated client.")
        return CalendarSyncResult(
            allowed=True,
            destination=self.destination,
            reason="confirmed",
            event_ids=tuple(event.event_id for event in events),
            **_sync_remote_events(self.client, calendar_id=self.calendar_id, events=events),
        )


class AppleCalendarAdapter:
    destination = "apple_calendar"
    side_effect = "external_calendar_write"

    def __init__(self, client: object | None = None, calendar_id: str = "default") -> None:
        self.client = client
        self.calendar_id = calendar_id

    def sync(self, events: tuple[DeadlineEvent, ...]) -> CalendarSyncResult:
        if self.client is None:
            raise RuntimeError("Apple Calendar adapter requires an authenticated CalDAV client.")
        return CalendarSyncResult(
            allowed=True,
            destination=self.destination,
            reason="confirmed",
            event_ids=tuple(event.event_id for event in events),
            **_sync_remote_events(self.client, calendar_id=self.calendar_id, events=events),
        )


def sync_calendar_draft(
    paths: Paths,
    draft: CalendarDraft,
    adapter: CalendarAdapter,
    *,
    confirmed: bool = False,
    confirmation_id: str = "",
    actor: str = "user",
) -> CalendarSyncResult:
    db.init_db(paths)
    plan = plan_calendar_sync(draft, destination=adapter.destination, confirmed=confirmed)
    allowed = bool(plan["allowed"])
    timestamp = utc_now()
    effective_confirmation_id = confirmation_id or _generated_confirmation_id("calendar-sync", timestamp)
    if not allowed:
        db.insert_audit_event(
            paths,
            action="calendar.sync.blocked",
            actor=actor,
            subject=adapter.destination,
            capability="calendar_write",
            side_effect=adapter.side_effect,
            allowed=False,
            confirmation_id=confirmation_id,
            metadata=plan,
            created_at=timestamp,
        )
        return CalendarSyncResult(
            allowed=False,
            destination=adapter.destination,
            reason=str(plan["reason"]),
            event_ids=tuple(event.event_id for event in draft.events),
        )

    if confirmation_id and db.approval_record_exists(
        paths,
        confirmation_id=confirmation_id,
        action="calendar.sync",
        subject=adapter.destination,
    ):
        replay_plan = {
            "allowed": False,
            "reason": "confirmation_id_already_consumed",
            "destination": adapter.destination,
            "event_count": len(draft.events),
            "confirmation_id": confirmation_id,
        }
        db.insert_audit_event(
            paths,
            action="calendar.sync.blocked",
            actor=actor,
            subject=adapter.destination,
            capability="calendar_write",
            side_effect=adapter.side_effect,
            allowed=False,
            confirmation_id=confirmation_id,
            metadata=replay_plan,
            created_at=timestamp,
        )
        return CalendarSyncResult(
            allowed=False,
            destination=adapter.destination,
            reason="confirmation_id_already_consumed",
            event_ids=tuple(event.event_id for event in draft.events),
        )

    result = adapter.sync(draft.events)
    db.insert_approval_record(
        paths,
        confirmation_id=effective_confirmation_id,
        actor=actor,
        action="calendar.sync",
        subject=adapter.destination,
        capability="calendar_write",
        side_effect=adapter.side_effect,
        status=result.reason,
        evidence_refs=_evidence_refs(draft.events),
        metadata={
            "event_ids": list(result.event_ids),
            "external_ids": list(result.external_ids),
            "created_external_ids": list(result.created_external_ids),
            "updated_external_ids": list(result.updated_external_ids),
            "output_path": result.output_path,
            "destination": result.destination,
        },
        created_at=timestamp,
        consumed_at=timestamp,
    )
    db.insert_audit_event(
        paths,
        action="calendar.sync",
        actor=actor,
        subject=adapter.destination,
        capability="calendar_write",
        side_effect=adapter.side_effect,
        allowed=True,
        confirmation_id=effective_confirmation_id,
        metadata={
            "event_ids": list(result.event_ids),
            "external_ids": list(result.external_ids),
            "created_external_ids": list(result.created_external_ids),
            "updated_external_ids": list(result.updated_external_ids),
            "output_path": result.output_path,
        },
        created_at=timestamp,
    )
    return result


def _generated_confirmation_id(prefix: str, timestamp: str) -> str:
    compact = "".join(ch for ch in timestamp if ch.isdigit())
    return f"{prefix}-{compact}"


def _evidence_refs(events: tuple[DeadlineEvent, ...]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for event in events:
        for value in (*event.source_ids, event.evidence_uri):
            if not value or value in seen:
                continue
            seen.add(value)
            refs.append(value)
    return refs


def _sync_remote_events(client: object, *, calendar_id: str, events: tuple[DeadlineEvent, ...]) -> dict[str, tuple[str, ...]]:
    existing = _list_existing_events(client, calendar_id=calendar_id)
    external_ids: list[str] = []
    created_ids: list[str] = []
    updated_ids: list[str] = []
    for event in events:
        match = _find_existing_event(existing, event)
        if match is not None:
            external_id = _external_id(match)
            if external_id and hasattr(client, "update_event"):
                updated = client.update_event(calendar_id=calendar_id, event_id=external_id, event=event)
                external_id = _external_id(updated) or external_id
                updated_ids.append(external_id)
            elif external_id:
                updated_ids.append(external_id)
            else:
                created = client.create_event(calendar_id=calendar_id, event=event)
                external_id = _external_id(created)
                created_ids.append(external_id)
            external_ids.append(external_id)
            continue
        created = client.create_event(calendar_id=calendar_id, event=event)
        external_id = _external_id(created)
        created_ids.append(external_id)
        external_ids.append(external_id)
    return {
        "external_ids": tuple(external_ids),
        "created_external_ids": tuple(created_ids),
        "updated_external_ids": tuple(updated_ids),
    }


def _list_existing_events(client: object, *, calendar_id: str) -> list[Any]:
    if not hasattr(client, "list_events"):
        return []
    try:
        result = client.list_events(calendar_id=calendar_id)
    except TypeError:
        result = client.list_events(calendar_id)
    if isinstance(result, dict):
        values = result.get("events") or result.get("items") or []
        return list(values) if isinstance(values, list) else []
    return list(result or [])


def _find_existing_event(existing: list[Any], event: DeadlineEvent) -> Any | None:
    for candidate in existing:
        if _matches_event(candidate, event):
            return candidate
    return None


def _matches_event(candidate: Any, event: DeadlineEvent) -> bool:
    if isinstance(candidate, DeadlineEvent):
        return candidate.event_id == event.event_id or (
            _norm(candidate.title) == _norm(event.title) and _norm(candidate.date_text) == _norm(event.date_text)
        )
    if not isinstance(candidate, dict):
        return False
    remote_event_id = str(candidate.get("lifeagent_event_id") or candidate.get("event_id") or candidate.get("uid") or "")
    if remote_event_id and remote_event_id == event.event_id:
        return True
    summary = str(candidate.get("summary") or candidate.get("title") or "")
    date_text = str(candidate.get("date_text") or candidate.get("date") or candidate.get("start_date") or "")
    start = candidate.get("start")
    if isinstance(start, dict):
        date_text = str(start.get("date") or start.get("dateTime") or date_text)
    return _norm(summary) == _norm(event.title) and _norm(date_text) == _norm(event.date_text)


def _external_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("id") or value.get("uid") or value.get("external_id") or value.get("event_id") or "")
    return str(value or "")


def _norm(value: str) -> str:
    return " ".join(str(value or "").lower().split())
