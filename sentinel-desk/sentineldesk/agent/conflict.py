from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sentineldesk import db
from sentineldesk.config import Paths
from sentineldesk.email.models import EmailFact


@dataclass(frozen=True)
class EvidenceFact:
    kind: str
    value: str
    source_id: str
    source_type: str
    trust_label: str
    evidence: str = ""
    confidence: float = 0.0
    observed_at: str = ""
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class SourceConflict:
    kind: str
    values: tuple[str, ...]
    facts: tuple[EmailFact | EvidenceFact, ...]
    safest_value: str | None = None

    @property
    def has_conflict(self) -> bool:
        return len(self.values) > 1


def detect_fact_conflict(facts: list[EmailFact | EvidenceFact], kind: str) -> SourceConflict:
    matching = [fact for fact in facts if fact.kind == kind]
    values = tuple(sorted({fact.value for fact in matching}))
    safest = _earliest_date(values) if kind == "deadline" else None
    return SourceConflict(kind=kind, values=values, facts=tuple(matching), safest_value=safest)


def collect_conflict_facts(paths: Paths, *, kind: str | None = None, limit: int = 500) -> list[EvidenceFact]:
    db.init_db(paths)
    facts: list[EvidenceFact] = []
    facts.extend(_email_facts(paths, kind=kind, limit=limit))
    facts.extend(_calendar_facts(paths, kind=kind, limit=limit))
    facts.extend(_portal_run_facts(paths, kind=kind, limit=limit))
    return facts


def detect_stored_conflict(paths: Paths, kind: str, *, limit: int = 500) -> SourceConflict:
    return detect_fact_conflict(collect_conflict_facts(paths, kind=kind, limit=limit), kind)


def _email_facts(paths: Paths, *, kind: str | None, limit: int) -> list[EvidenceFact]:
    rows = db.list_email_facts(paths, kind=kind, limit=limit)
    return [
        EvidenceFact(
            kind=str(row.get("kind") or ""),
            value=str(row.get("value") or ""),
            source_id=str(row.get("source_id") or ""),
            source_type=str(row.get("source_type") or "email"),
            trust_label=str(row.get("trust_label") or "email_unverified"),
            evidence=str(row.get("evidence") or ""),
            confidence=float(row.get("confidence") or 0.0),
            observed_at=str(row.get("received_at") or row.get("message_received_at") or ""),
            metadata={
                "message_id": row.get("message_id"),
                "thread_id": row.get("thread_id"),
                "subject": row.get("subject"),
            },
        )
        for row in rows
        if row.get("kind") and row.get("value")
    ]


def _calendar_facts(paths: Paths, *, kind: str | None, limit: int) -> list[EvidenceFact]:
    if kind not in {None, "deadline"}:
        return []
    rows = db.list_calendar_drafts(paths, limit=limit)
    return [
        EvidenceFact(
            kind="deadline",
            value=str(row.get("date_text") or ""),
            source_id=f"calendar:{row.get('event_id') or ''}",
            source_type="calendar_draft",
            trust_label=str(row.get("sync_state") or "local_draft"),
            evidence=str(row.get("evidence_uri") or ""),
            confidence=float(row.get("confidence") or 0.0),
            observed_at=str(row.get("updated_at") or row.get("created_at") or ""),
            metadata={
                "title": row.get("title"),
                "status": row.get("status"),
                "source_ids": row.get("source_ids", []),
            },
        )
        for row in rows
        if row.get("date_text")
    ]


def _portal_run_facts(paths: Paths, *, kind: str | None, limit: int) -> list[EvidenceFact]:
    rows = db.list_runs(paths, limit=limit)
    facts: list[EvidenceFact] = []
    for row in rows:
        trust_label = "portal_verified" if row.get("health", {}).get("state") == "ok" else "portal_uncertain"
        evidence_path = str(row.get("evidence", {}).get("path") or "")
        observed_at = str(row.get("captured_at") or "")
        run_id = str(row.get("run_id") or "")
        if kind in {None, "status"} and row.get("status", {}).get("value"):
            facts.append(
                EvidenceFact(
                    kind="status",
                    value=str(row.get("status", {}).get("value") or ""),
                    source_id=f"portal_run:{run_id}",
                    source_type="portal_run",
                    trust_label=trust_label,
                    evidence=evidence_path,
                    confidence=float(row.get("status", {}).get("confidence") or 0.0),
                    observed_at=observed_at,
                    metadata={"alert": row.get("alert", {})},
                )
            )
        if kind in {None, "deadline"}:
            for deadline in row.get("deadlines", []) or []:
                if not isinstance(deadline, dict) or not deadline.get("date_text"):
                    continue
                facts.append(
                    EvidenceFact(
                        kind="deadline",
                        value=str(deadline.get("date_text") or ""),
                        source_id=f"portal_run:{run_id}",
                        source_type="portal_run",
                        trust_label=trust_label,
                        evidence=str(deadline.get("context") or evidence_path),
                        confidence=float(deadline.get("confidence") or 0.0),
                        observed_at=observed_at,
                        metadata={"alert": row.get("alert", {})},
                    )
                )
    return facts


def _earliest_date(values: tuple[str, ...]) -> str | None:
    parsed: list[tuple[datetime, str]] = []
    for value in values:
        date = _parse_date(value)
        if date:
            parsed.append((date, value))
    if not parsed:
        return None
    parsed.sort(key=lambda item: item[0])
    return parsed[0][1]


def _parse_date(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
