"""Run a verification suite, status-roll it up, and persist the report/artifact."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from sentineldesk import db
from sentineldesk.config import Paths
from sentineldesk.extract import utc_now

from .checks import _calendar_checks, _gmail_checks, _langgraph_checks, _sandbox_checks
from .models import VerificationCheck, VerificationReport


def run_verification(
    paths: Paths,
    *,
    suite: str = "all",
    account_id: str = "default",
    google_credentials_env: str = "SENTINEL_GOOGLE_CREDENTIALS_JSON",
    google_token_env: str = "SENTINEL_GOOGLE_TOKEN_JSON",
    apple_user_env: str = "SENTINEL_APPLE_ID",
    apple_password_env: str = "SENTINEL_APPLE_APP_PASSWORD",
    persist: bool = True,
    created_at: str | None = None,
) -> VerificationReport:
    db.init_db(paths)
    timestamp = created_at or utc_now()
    checks: list[VerificationCheck] = []
    requested = {suite} if suite != "all" else {"gmail", "calendar", "langgraph"}
    if "gmail" in requested:
        checks.extend(_gmail_checks(paths, account_id, google_credentials_env, google_token_env))
    if "calendar" in requested:
        checks.extend(_calendar_checks(paths, account_id, google_credentials_env, google_token_env, apple_user_env, apple_password_env))
    if "langgraph" in requested:
        checks.extend(_langgraph_checks(paths))
    if "sandbox" in requested:
        checks.extend(_sandbox_checks(paths, account_id, timestamp))
    status = _report_status(checks)
    base_verification_id = f"{timestamp.replace(':', '').replace('-', '').replace('.', '')}-{suite}"
    verification_id = _unique_verification_id(paths, base_verification_id) if persist else base_verification_id
    artifact_path = ""
    report = VerificationReport(
        verification_id=verification_id,
        suite=suite,
        status=status,
        checks=tuple(checks),
        artifact_path="",
        created_at=timestamp,
    )
    if persist:
        artifact_path = str(_artifact_path(paths, verification_id))
        report = VerificationReport(
            verification_id=verification_id,
            suite=suite,
            status=status,
            checks=tuple(checks),
            artifact_path=artifact_path,
            created_at=timestamp,
        )
        _write_artifact(paths, report)
        db.insert_integration_verification(
            paths,
            verification_id=verification_id,
            suite=suite,
            status=status,
            checks=[asdict(check) for check in checks],
            artifact_path=artifact_path,
            created_at=timestamp,
        )
        db.insert_audit_event(
            paths,
            action="integration.verify",
            actor="system",
            subject=suite,
            capability="integration_readiness",
            side_effect="local_db_write",
            allowed=True,
            confirmation_id="",
            metadata={"status": status, "verification_id": verification_id},
            created_at=timestamp,
        )
    return report


def _report_status(checks: list[VerificationCheck]) -> str:
    if not checks:
        return "empty"
    if all(check.status == "ready" for check in checks):
        return "ready"
    if any(check.status == "ready" for check in checks):
        return "partial"
    return "missing"


def _write_artifact(paths: Paths, report: VerificationReport) -> Path:
    destination = _artifact_path(paths, report.verification_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return destination


def _artifact_path(paths: Paths, verification_id: str) -> Path:
    return paths.artifacts / "integrations" / f"{verification_id}.json"


def _unique_verification_id(paths: Paths, base: str) -> str:
    if not db.get_integration_verification(paths, base) and not _artifact_path(paths, base).exists():
        return base
    for counter in range(2, 10000):
        candidate = f"{base}-{counter}"
        if not db.get_integration_verification(paths, candidate) and not _artifact_path(paths, candidate).exists():
            return candidate
    raise RuntimeError(f"Unable to allocate unique verification id for {base}")
