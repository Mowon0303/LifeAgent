from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import db
from .config import Paths
from .extract import utc_now


SOURCE_TABLES = {
    "email": ("email_messages", "ingested_at"),
    "calendar": ("calendar_drafts", "updated_at"),
    "tasks": ("task_reviews", "updated_at"),
    "audit": ("audit_events", "created_at"),
    "approvals": ("approval_records", "created_at"),
}


@dataclass(frozen=True)
class RetentionResult:
    before: str
    sources: tuple[str, ...]
    dry_run: bool
    deleted: bool
    counts: dict[str, int]


def plan_purge(paths: Paths, *, before: str, sources: tuple[str, ...] = ("email", "calendar", "tasks", "audit", "approvals")) -> RetentionResult:
    return RetentionResult(before=before, sources=sources, dry_run=True, deleted=False, counts=_counts(paths, before, sources))


def purge(
    paths: Paths,
    *,
    before: str,
    sources: tuple[str, ...] = ("email", "calendar", "tasks", "audit", "approvals"),
    confirmed: bool = False,
    actor: str = "user",
) -> RetentionResult:
    counts = _counts(paths, before, sources)
    if not confirmed:
        raise PermissionError("Retention purge requires explicit confirmation.")
    with db.open_db(paths) as conn:
        for source in sources:
            table, column = _table_for(source)
            conn.execute(f"DELETE FROM {table} WHERE {column} < ?", (before,))
    db.insert_audit_event(
        paths,
        action="retention.purge",
        actor=actor,
        subject=",".join(sources),
        capability="data_delete",
        side_effect="local_delete",
        allowed=True,
        confirmation_id="retention_confirmed",
        metadata={"before": before, "counts": counts},
        created_at=utc_now(),
    )
    return RetentionResult(before=before, sources=sources, dry_run=False, deleted=True, counts=counts)


def _counts(paths: Paths, before: str, sources: tuple[str, ...]) -> dict[str, int]:
    db.init_db(paths)
    result: dict[str, int] = {}
    with db.open_db(paths) as conn:
        for source in sources:
            table, column = _table_for(source)
            row = conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE {column} < ?", (before,)).fetchone()
            result[source] = int(row["count"] if row else 0)
    return result


def _table_for(source: str) -> tuple[str, str]:
    try:
        return SOURCE_TABLES[source]
    except KeyError as exc:
        raise ValueError(f"Unknown retention source: {source}") from exc


def result_to_dict(result: RetentionResult) -> dict[str, Any]:
    return {
        "before": result.before,
        "sources": list(result.sources),
        "dry_run": result.dry_run,
        "deleted": result.deleted,
        "counts": result.counts,
    }
