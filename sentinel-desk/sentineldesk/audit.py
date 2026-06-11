from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import db
from .config import Paths
from .extract import utc_now


@dataclass(frozen=True)
class AuditEvent:
    action: str
    actor: str = "system"
    subject: str = ""
    capability: str = ""
    side_effect: str = "none"
    allowed: bool = True
    confirmation_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


def record_event(paths: Paths, event: AuditEvent) -> int:
    db.init_db(paths)
    return db.insert_audit_event(
        paths,
        action=event.action,
        actor=event.actor,
        subject=event.subject,
        capability=event.capability,
        side_effect=event.side_effect,
        allowed=event.allowed,
        confirmation_id=event.confirmation_id,
        metadata=event.metadata,
        created_at=event.created_at or utc_now(),
    )


def list_events(paths: Paths, *, limit: int = 100) -> list[dict[str, Any]]:
    return db.list_audit_events(paths, limit=limit)
