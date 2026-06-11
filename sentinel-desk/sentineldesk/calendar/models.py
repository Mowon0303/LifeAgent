from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReminderRule:
    days_before: int
    method: str = "display"


@dataclass(frozen=True)
class DeadlineEvent:
    title: str
    date_text: str
    source_ids: tuple[str, ...]
    severity: str = "medium"
    confidence: float = 0.0
    status: str = "draft"
    evidence_uri: str = ""
    reminders: tuple[ReminderRule, ...] = (
        ReminderRule(14),
        ReminderRule(7),
        ReminderRule(1),
    )
    event_id: str = field(default="")

    def __post_init__(self) -> None:
        if self.event_id:
            return
        key = "|".join([normalize_key(self.title), normalize_key(self.date_text), *sorted(self.source_ids)])
        object.__setattr__(self, "event_id", hashlib.sha256(key.encode("utf-8")).hexdigest()[:16])


@dataclass(frozen=True)
class CalendarDraft:
    events: tuple[DeadlineEvent, ...]
    requires_confirmation: bool = True
    destination: str = "local-preview"


def normalize_key(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()
