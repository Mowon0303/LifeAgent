from __future__ import annotations

import importlib.util
import json
import base64
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sentineldesk import db
from sentineldesk.agent.model import load_model_provider
from sentineldesk.agent.workflow import build_langgraph_workflow, runtime_for
from sentineldesk.calendar.adapters import AppleCalendarAdapter, GoogleCalendarAdapter, sync_calendar_draft
from sentineldesk.calendar.models import CalendarDraft, DeadlineEvent
from sentineldesk.config import Paths
from sentineldesk.email.connectors import EmailSyncRequest, GmailApiEmailConnector
from sentineldesk.email.ingest import sync_connector
from sentineldesk.extract import utc_now
from sentineldesk.integrations.apple_calendar import APPLE_CALDAV_URL
from sentineldesk.integrations.google_workspace import CALENDAR_EVENTS_SCOPE, GMAIL_READONLY_SCOPE
from sentineldesk.privacy import audit_project_tree, audit_redacted_artifacts
from sentineldesk.secrets import SecretUnavailable, env_secret, resolve_secret, secret_status


DEFAULT_SOURCE_RELEASE_PATH = "/tmp/extracted-sentineldesk"


@dataclass(frozen=True)
class VerificationCheck:
    name: str
    status: str
    detail: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class VerificationReport:
    verification_id: str
    suite: str
    status: str
    checks: tuple[VerificationCheck, ...]
    artifact_path: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "verification_id": self.verification_id,
            "suite": self.suite,
            "status": self.status,
            "checks": [asdict(check) for check in self.checks],
            "artifact_path": self.artifact_path,
            "created_at": self.created_at,
        }


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


def build_completion_audit(
    paths: Paths,
    *,
    account_id: str = "default",
    google_credentials_env: str = "SENTINEL_GOOGLE_CREDENTIALS_JSON",
    google_token_env: str = "SENTINEL_GOOGLE_TOKEN_JSON",
    apple_user_env: str = "SENTINEL_APPLE_ID",
    apple_password_env: str = "SENTINEL_APPLE_APP_PASSWORD",
    source_release_path: str = DEFAULT_SOURCE_RELEASE_PATH,
) -> dict[str, Any]:
    current = run_verification(
        paths,
        suite="all",
        account_id=account_id,
        google_credentials_env=google_credentials_env,
        google_token_env=google_token_env,
        apple_user_env=apple_user_env,
        apple_password_env=apple_password_env,
        persist=False,
    )
    current_checks = [asdict(check) for check in current.checks]
    missing_checks = [check for check in current_checks if check.get("status") != "ready"]
    latest_all = _latest_all_report(paths)
    latest_package = _latest_package_status(paths, latest_all)
    redacted_privacy = _redacted_output_privacy_status(paths)
    source_release = _source_release_audit_status(Path(source_release_path))
    requirements = [
        {
            "name": "current_all_readiness",
            "status": "ready" if current.status == "ready" else "missing",
            "detail": "All live readiness checks are ready." if current.status == "ready" else "One or more live readiness checks are missing.",
            "missing_checks": [check["name"] for check in missing_checks],
        },
        latest_package,
        redacted_privacy,
        source_release,
    ]
    missing_requirements = [item for item in requirements if item["status"] != "ready"]
    return {
        "ready": not missing_requirements,
        "account_id": account_id,
        "current_report": current.to_dict(),
        "requirements": requirements,
        "missing_requirements": missing_requirements,
        "readiness_action_plan": _readiness_action_plan(
            account_id=account_id,
            current_checks=current_checks,
            requirements=requirements,
            google_credentials_env=google_credentials_env,
            google_token_env=google_token_env,
            apple_user_env=apple_user_env,
            apple_password_env=apple_password_env,
            source_release_path=source_release_path,
        ),
        "latest_all_report": latest_all or {},
        "next_commands": _completion_next_commands(account_id),
        "privacy": "Completion audit uses redacted env refs, connector cursor metadata, approval records, package existence, and redacted-output privacy scan only; it does not call external services.",
    }


def format_handoff_checklist(audit: dict[str, Any]) -> str:
    """Render a human-readable live verification checklist from a completion audit."""
    account_id = str(audit.get("account_id") or "default")
    ready = bool(audit.get("ready"))
    lines = [
        "# LifeAgent Live Verification Handoff",
        "",
        f"- Account: `{account_id}`",
        f"- Overall status: `{'ready' if ready else 'not_ready'}`",
        "- Privacy: this checklist is generated from redacted env refs, connector metadata, approval records, and local package/audit state only.",
        "",
        "## Completion Gates",
        "",
    ]
    for requirement in audit.get("requirements") or []:
        status = str(requirement.get("status") or "missing")
        lines.append(f"- {_checkbox(status)} `{requirement.get('name')}` - {requirement.get('detail', '')}")
        missing = [str(item) for item in requirement.get("missing_checks") or []]
        if missing:
            lines.append(f"  Missing checks: `{', '.join(missing)}`")
    lines.extend(["", "## Action Checklist", ""])
    for action in audit.get("readiness_action_plan") or []:
        status = str(action.get("status") or "missing")
        approval = "yes" if action.get("requires_user_approval") else "no"
        lines.append(f"### {_checkbox(status)} `{action.get('id')}`")
        lines.append("")
        lines.append(str(action.get("description") or ""))
        lines.append("")
        lines.append(f"- Side effect: `{action.get('side_effect', 'local_only')}`")
        lines.append(f"- Requires user approval: `{approval}`")
        missing = [str(item) for item in action.get("missing_checks") or []]
        if missing:
            lines.append(f"- Missing checks: `{', '.join(missing)}`")
        commands = [str(command) for command in action.get("commands") or []]
        if commands:
            lines.append("")
            lines.append("```bash")
            lines.extend(commands)
            lines.append("```")
        lines.append("")
    lines.extend(
        [
            "## Final Command Sequence",
            "",
            "```bash",
            *[str(command) for command in audit.get("next_commands") or []],
            "```",
            "",
            "## Safety Notes",
            "",
            "- `external_read` steps read from a user-approved account and should be run only after approval.",
            "- `external_calendar_write` steps write to Google or Apple Calendar and require explicit confirmation IDs.",
            "- Secrets should stay in environment variables or local token files; do not paste token values into reports or issues.",
            "- Treat the plan as complete only after all completion gates are checked and the final source release audit passes.",
            "",
        ]
    )
    return "\n".join(lines)


def _checkbox(status: str) -> str:
    return "[x]" if status == "ready" else "[ ]"


def _gmail_checks(paths: Paths, account_id: str, credentials_env: str, token_env: str) -> list[VerificationCheck]:
    state = db.get_connector_state(paths, connector="gmail_api", account_id=account_id)
    return [
        _secret_check("gmail.credentials", credentials_env),
        _google_credentials_format_check("gmail.credentials_format", credentials_env),
        _secret_check("gmail.token", token_env),
        _google_token_format_check("gmail.token_format", token_env),
        _token_scope_check("gmail.token_scope", token_env, (GMAIL_READONLY_SCOPE,)),
        _module_check("gmail.googleapiclient", "googleapiclient.discovery"),
        _module_check("gmail.oauth_credentials", "google.oauth2.credentials"),
        _module_check("gmail.oauth_flow", "google_auth_oauthlib.flow"),
        VerificationCheck(
            name="gmail.scope",
            status="ready",
            detail="Gmail readonly scope is configured.",
            metadata={"scope": GMAIL_READONLY_SCOPE},
        ),
        VerificationCheck(
            name="gmail.cursor",
            status="ready" if state and state.get("cursor") else "missing",
            detail="Stored Gmail cursor found." if state and state.get("cursor") else "No stored Gmail cursor yet.",
            metadata={"account_id": account_id, "connector": "gmail_api", "has_cursor": bool(state and state.get("cursor"))},
        ),
    ]


def _calendar_checks(
    paths: Paths,
    account_id: str,
    google_credentials_env: str,
    google_token_env: str,
    apple_user_env: str,
    apple_password_env: str,
) -> list[VerificationCheck]:
    return [
        _secret_check("google_calendar.credentials", google_credentials_env),
        _google_credentials_format_check("google_calendar.credentials_format", google_credentials_env),
        _secret_check("google_calendar.token", google_token_env),
        _google_token_format_check("google_calendar.token_format", google_token_env),
        _token_scope_check("google_calendar.token_scope", google_token_env, (CALENDAR_EVENTS_SCOPE,)),
        _module_check("google_calendar.googleapiclient", "googleapiclient.discovery"),
        _module_check("google_calendar.oauth_flow", "google_auth_oauthlib.flow"),
        VerificationCheck(
            name="google_calendar.scope",
            status="ready",
            detail="Google Calendar events scope is configured.",
            metadata={"scope": CALENDAR_EVENTS_SCOPE, "account_id": account_id},
        ),
        _calendar_sync_evidence_check(paths, "google_calendar.sync_evidence", "google_calendar"),
        _secret_check("apple_calendar.username", apple_user_env),
        _apple_username_format_check("apple_calendar.username_format", apple_user_env),
        _secret_check("apple_calendar.app_password", apple_password_env),
        _apple_app_password_format_check("apple_calendar.app_password_format", apple_password_env),
        _module_check("apple_calendar.caldav", "caldav"),
        VerificationCheck(
            name="apple_calendar.endpoint",
            status="ready",
            detail="Apple CalDAV endpoint is configured.",
            metadata={"caldav_url": APPLE_CALDAV_URL},
        ),
        _calendar_sync_evidence_check(paths, "apple_calendar.sync_evidence", "apple_calendar"),
    ]


def _langgraph_checks(paths: Paths) -> list[VerificationCheck]:
    provider = load_model_provider(paths)
    runtime = runtime_for(provider)
    runnable = build_langgraph_workflow() if runtime.engine == "langgraph" else None
    return [
        _module_check("langgraph.module", "langgraph.graph"),
        VerificationCheck(
            name="langgraph.runtime",
            status="ready" if runtime.engine == "langgraph" and runnable is not None else "missing",
            detail="LangGraph workflow is buildable." if runnable is not None else "LangGraph is not installed or workflow could not be built.",
            metadata={
                "engine": runtime.engine,
                "reason": runtime.reason,
                "provider": provider.provider,
                "model": provider.model,
            },
        ),
    ]


def _sandbox_checks(paths: Paths, account_id: str, timestamp: str) -> list[VerificationCheck]:
    sandbox_id = _compact_id(timestamp)
    gmail_client = _SandboxGmailClient(account_id=account_id, message_id=f"sandbox-gmail-{sandbox_id}")
    gmail_summary = sync_connector(
        paths,
        GmailApiEmailConnector(gmail_client),
        EmailSyncRequest(query="deadline", since="sandbox-history-0", limit=5),
        account_id=account_id,
        ingested_at=timestamp,
    )

    event = DeadlineEvent(
        title="Sandbox deadline",
        date_text="2026-07-15",
        source_ids=(f"gmail:{gmail_client.message_id}",),
        evidence_uri=f"gmail:{gmail_client.message_id}",
    )
    draft = CalendarDraft((event,))

    google_client = _SandboxCalendarClient("sandbox-google-event")
    google_adapter = GoogleCalendarAdapter(google_client)
    google_blocked = sync_calendar_draft(paths, draft, google_adapter, confirmed=False, actor="sandbox")
    google_allowed = sync_calendar_draft(
        paths,
        draft,
        google_adapter,
        confirmed=True,
        confirmation_id=f"sandbox-google-{sandbox_id}",
        actor="sandbox",
    )

    apple_client = _SandboxCalendarClient("sandbox-apple-event")
    apple_adapter = AppleCalendarAdapter(apple_client, calendar_id="sandbox-icloud")
    apple_blocked = sync_calendar_draft(paths, draft, apple_adapter, confirmed=False, actor="sandbox")
    apple_allowed = sync_calendar_draft(
        paths,
        draft,
        apple_adapter,
        confirmed=True,
        confirmation_id=f"sandbox-apple-{sandbox_id}",
        actor="sandbox",
    )

    approvals = db.list_approval_records(paths, limit=20)
    return [
        VerificationCheck(
            name="sandbox.gmail_sync",
            status="ready" if gmail_summary["cursor_saved"] and gmail_summary["messages_persisted"] == 1 else "missing",
            detail="Sandbox Gmail connector sync exercised cursor persistence, email ingest, and deadline extraction.",
            metadata={
                "connector": gmail_summary["connector"],
                "account_id": gmail_summary["account_id"],
                "cursor_saved": gmail_summary["cursor_saved"],
                "scopes": gmail_summary["scopes"],
                "messages_persisted": gmail_summary["messages_persisted"],
                "facts_extracted": gmail_summary["facts_extracted"],
                "deadline_events_drafted": gmail_summary["deadline_events_drafted"],
            },
        ),
        VerificationCheck(
            name="sandbox.google_calendar_confirmation",
            status="ready" if (not google_blocked.allowed and google_allowed.allowed and google_client.created) else "missing",
            detail="Sandbox Google Calendar adapter exercised blocked write, confirmed write, audit, and approval record paths.",
            metadata={
                "blocked_reason": google_blocked.reason,
                "allowed": google_allowed.allowed,
                "external_ids": list(google_allowed.external_ids),
                "created_count": len(google_client.created),
                "confirmation_id": f"sandbox-google-{sandbox_id}",
            },
        ),
        VerificationCheck(
            name="sandbox.apple_calendar_confirmation",
            status="ready" if (not apple_blocked.allowed and apple_allowed.allowed and apple_client.created) else "missing",
            detail="Sandbox Apple Calendar adapter exercised blocked write, confirmed write, audit, and approval record paths.",
            metadata={
                "blocked_reason": apple_blocked.reason,
                "allowed": apple_allowed.allowed,
                "external_ids": list(apple_allowed.external_ids),
                "created_count": len(apple_client.created),
                "confirmation_id": f"sandbox-apple-{sandbox_id}",
            },
        ),
        VerificationCheck(
            name="sandbox.approval_records",
            status="ready" if len([item for item in approvals if str(item.get("confirmation_id", "")).startswith("sandbox-")]) >= 2 else "missing",
            detail="Sandbox confirmed calendar writes created durable approval records.",
            metadata={
                "sandbox_approval_count": len([item for item in approvals if str(item.get("confirmation_id", "")).startswith("sandbox-")]),
                "approval_actions": [item.get("action") for item in approvals[:5]],
            },
        ),
    ]


def _secret_check(name: str, env_name: str) -> VerificationCheck:
    status = secret_status(env_secret(env_name))
    return VerificationCheck(
        name=name,
        status="ready" if status["available"] else "missing",
        detail=f"Environment secret {env_name} is {'available' if status['available'] else 'missing'}.",
        metadata=status,
    )


def _google_credentials_format_check(name: str, env_name: str) -> VerificationCheck:
    ref = env_secret(env_name)
    status = secret_status(ref)
    try:
        info = _load_secret_json(ref)
    except SecretUnavailable:
        return VerificationCheck(
            name=name,
            status="missing" if not status["available"] else "invalid",
            detail=(
                f"Google OAuth credentials JSON {env_name} is missing."
                if not status["available"]
                else f"Google OAuth credentials JSON {env_name} is not valid JSON or base64 JSON."
            ),
            metadata={"credentials": ref.redacted, "available": status["available"], "json_parseable": False},
        )
    client_type = "installed" if isinstance(info.get("installed"), dict) else "web" if isinstance(info.get("web"), dict) else ""
    client = info.get(client_type) if client_type else {}
    required_fields = ["client_id", "auth_uri", "token_uri"]
    missing_fields = [field for field in required_fields if not isinstance(client, dict) or not client.get(field)]
    return VerificationCheck(
        name=name,
        status="ready" if client_type and not missing_fields else "invalid",
        detail=(
            "Google OAuth credentials JSON has a supported client config."
            if client_type and not missing_fields
            else "Google OAuth credentials JSON must contain an installed or web client with required OAuth fields."
        ),
        metadata={
            "credentials": ref.redacted,
            "available": True,
            "json_parseable": True,
            "client_type": client_type,
            "missing_fields": missing_fields,
        },
    )


def _google_token_format_check(name: str, token_env: str) -> VerificationCheck:
    ref = env_secret(token_env)
    status = secret_status(ref)
    try:
        token_info = _load_secret_json(ref)
    except SecretUnavailable:
        return VerificationCheck(
            name=name,
            status="missing" if not status["available"] else "invalid",
            detail=(
                f"Google authorized token JSON {token_env} is missing."
                if not status["available"]
                else f"Google authorized token JSON {token_env} is not valid JSON or base64 JSON."
            ),
            metadata={"token": ref.redacted, "available": status["available"], "json_parseable": False},
        )
    has_access_token = bool(token_info.get("token") or token_info.get("access_token"))
    required_fields = ["refresh_token", "token_uri", "client_id", "client_secret"]
    missing_fields = [field for field in required_fields if not token_info.get(field)]
    if not has_access_token:
        missing_fields.insert(0, "token")
    return VerificationCheck(
        name=name,
        status="ready" if not missing_fields else "invalid",
        detail=(
            "Google authorized token JSON has the fields needed for API clients."
            if not missing_fields
            else "Google authorized token JSON is missing one or more required fields."
        ),
        metadata={
            "token": ref.redacted,
            "available": True,
            "json_parseable": True,
            "missing_fields": missing_fields,
            "has_scope_metadata": bool(_extract_token_scopes(token_info)),
        },
    )


def _apple_username_format_check(name: str, user_env: str) -> VerificationCheck:
    ref = env_secret(user_env)
    status = secret_status(ref)
    try:
        raw = resolve_secret(ref)
    except SecretUnavailable:
        return VerificationCheck(
            name=name,
            status="missing",
            detail=f"Apple Calendar username {user_env} is missing.",
            metadata={"username": ref.redacted, "available": status["available"], "contains_at": False},
        )
    stripped = raw.strip()
    contains_whitespace = stripped != raw or any(char.isspace() for char in stripped)
    local_part, separator, domain_part = stripped.partition("@")
    contains_at = bool(separator)
    domain_has_dot = "." in domain_part
    valid = bool(local_part and domain_part and contains_at and domain_has_dot and not contains_whitespace)
    return VerificationCheck(
        name=name,
        status="ready" if valid else "invalid",
        detail=(
            "Apple Calendar username looks like an Apple ID email address."
            if valid
            else "Apple Calendar username should be an Apple ID email address without whitespace."
        ),
        metadata={
            "username": ref.redacted,
            "available": True,
            "contains_at": contains_at,
            "domain_has_dot": domain_has_dot,
            "contains_whitespace": contains_whitespace,
        },
    )


def _apple_app_password_format_check(name: str, password_env: str) -> VerificationCheck:
    ref = env_secret(password_env)
    status = secret_status(ref)
    try:
        raw = resolve_secret(ref)
    except SecretUnavailable:
        return VerificationCheck(
            name=name,
            status="missing",
            detail=f"Apple app-specific password {password_env} is missing.",
            metadata={"app_password": ref.redacted, "available": status["available"], "normalized_length": 0},
        )
    stripped = raw.strip()
    contains_whitespace = stripped != raw or any(char.isspace() for char in stripped)
    groups = stripped.split("-")
    dashed_format = len(groups) == 4 and all(len(group) == 4 and group.isalnum() for group in groups)
    compact_format = len(stripped) == 16 and stripped.isalnum()
    normalized_length = len(stripped.replace("-", ""))
    valid = not contains_whitespace and (dashed_format or compact_format)
    return VerificationCheck(
        name=name,
        status="ready" if valid else "invalid",
        detail=(
            "Apple app-specific password has a compatible local format."
            if valid
            else "Apple app-specific password should be four 4-character groups or a compact 16-character value without whitespace."
        ),
        metadata={
            "app_password": ref.redacted,
            "available": True,
            "normalized_length": normalized_length,
            "dash_group_count": len(groups) if "-" in stripped else 0,
            "dashed_format": dashed_format,
            "compact_format": compact_format,
            "contains_whitespace": contains_whitespace,
        },
    )


def _token_scope_check(name: str, token_env: str, required_scopes: tuple[str, ...]) -> VerificationCheck:
    ref = env_secret(token_env)
    try:
        token_info = _load_secret_json(ref)
    except SecretUnavailable:
        return VerificationCheck(
            name=name,
            status="missing",
            detail=f"Google token scope check could not read {token_env}.",
            metadata={"token": ref.redacted, "required_scopes": list(required_scopes), "scopes_present": [], "missing_scopes": list(required_scopes)},
        )
    scopes = _extract_token_scopes(token_info)
    missing = [scope for scope in required_scopes if scope not in scopes]
    return VerificationCheck(
        name=name,
        status="ready" if not missing else "missing",
        detail="Google token includes required OAuth scope." if not missing else "Google token is missing one or more required OAuth scopes.",
        metadata={
            "token": ref.redacted,
            "required_scopes": list(required_scopes),
            "scopes_present": scopes,
            "missing_scopes": missing,
            "token_json_parseable": True,
        },
    )


def _load_secret_json(ref: Any) -> dict[str, Any]:
    raw = resolve_secret(ref)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        try:
            parsed = json.loads(base64.b64decode(raw).decode("utf-8"))
        except Exception as exc:
            raise SecretUnavailable(f"Secret {ref.redacted} is not JSON or base64 JSON.") from exc
    if not isinstance(parsed, dict):
        raise SecretUnavailable(f"Secret {ref.redacted} must be a JSON object.")
    return parsed


def _extract_token_scopes(token_info: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("scopes", "scope", "granted_scopes", "grantedScopes"):
        value = token_info.get(key)
        if isinstance(value, str):
            values.extend(item.strip() for chunk in value.split(",") for item in chunk.split() if item.strip())
        elif isinstance(value, (list, tuple)):
            values.extend(str(item).strip() for item in value if str(item).strip())
    return list(dict.fromkeys(values))


def _calendar_sync_evidence_check(paths: Paths, name: str, subject: str) -> VerificationCheck:
    approvals = [
        item
        for item in db.list_approval_records(paths, limit=200)
        if item.get("action") == "calendar.sync"
        and item.get("subject") == subject
        and item.get("side_effect") == "external_calendar_write"
        and item.get("actor") != "sandbox"
    ]
    latest = approvals[0] if approvals else {}
    metadata = {
        "subject": subject,
        "has_approval": bool(approvals),
        "approval_count": len(approvals),
        "latest_confirmation_id": latest.get("confirmation_id", ""),
        "latest_status": latest.get("status", ""),
        "latest_created_at": latest.get("created_at", ""),
        "external_ids": (latest.get("metadata") or {}).get("external_ids", []) if latest else [],
        "created_external_ids": (latest.get("metadata") or {}).get("created_external_ids", []) if latest else [],
        "updated_external_ids": (latest.get("metadata") or {}).get("updated_external_ids", []) if latest else [],
    }
    return VerificationCheck(
        name=name,
        status="ready" if approvals else "missing",
        detail=f"Confirmed {subject} sync evidence found." if approvals else f"No confirmed {subject} sync evidence found yet.",
        metadata=metadata,
    )


def build_env_template(
    *,
    account_id: str = "user@example.com",
    google_credentials_env: str = "SENTINEL_GOOGLE_CREDENTIALS_JSON",
    google_token_env: str = "SENTINEL_GOOGLE_TOKEN_JSON",
    apple_user_env: str = "SENTINEL_APPLE_ID",
    apple_password_env: str = "SENTINEL_APPLE_APP_PASSWORD",
) -> dict[str, Any]:
    env_refs = [
        {
            "name": google_credentials_env,
            "purpose": "Google OAuth client credentials JSON for Gmail and Google Calendar.",
            "scope": "gmail.readonly + calendar.events",
            "status": secret_status(env_secret(google_credentials_env)),
        },
        {
            "name": google_token_env,
            "purpose": "Google authorized user token JSON for Gmail and Google Calendar.",
            "scope": "gmail.readonly + calendar.events",
            "status": secret_status(env_secret(google_token_env)),
        },
        {
            "name": apple_user_env,
            "purpose": "Apple ID username for CalDAV calendar checks.",
            "scope": "calendar CalDAV",
            "status": secret_status(env_secret(apple_user_env)),
        },
        {
            "name": apple_password_env,
            "purpose": "Apple app-specific password for CalDAV calendar checks.",
            "scope": "calendar CalDAV",
            "status": secret_status(env_secret(apple_password_env)),
        },
    ]
    return {
        "privacy": "This template reports secret availability and redacted refs only; it never prints secret values.",
        "required_env": env_refs,
        "install_commands": [
            "python3 -B -m venv .agent-venv",
            ".agent-venv/bin/python -m pip install -e '.[agent,integrations]'",
        ],
        "verification_commands": [
            f".agent-venv/bin/python -B -m sentineldesk --home .demo integrations handoff --account {account_id} --output .demo/live-verification-handoff.md",
            f".agent-venv/bin/python -B -m sentineldesk --home .demo integrations check --suite all --account {account_id} --require-ready",
            f".agent-venv/bin/python -B -m sentineldesk --home .demo integrations check --suite gmail --account {account_id} --require-ready",
            f".agent-venv/bin/python -B -m sentineldesk --home .demo integrations check --suite calendar --account {account_id} --require-ready",
            ".agent-venv/bin/python -B -m sentineldesk --home .demo privacy release-package --source . --output /tmp/sentineldesk.release.zip",
            "python3 -B -m zipfile -e /tmp/sentineldesk.release.zip /tmp/extracted-sentineldesk",
            ".agent-venv/bin/python -B -m sentineldesk --home .demo privacy release-audit --path /tmp/extracted-sentineldesk --require-clean",
            f".agent-venv/bin/python -B -m sentineldesk --home .demo integrations completion-audit --account {account_id} --source-release-path /tmp/extracted-sentineldesk --require-ready",
            ".agent-venv/bin/python -B -m sentineldesk --home .demo privacy audit --require-clean",
        ],
        "auth_commands": [
            f".agent-venv/bin/python -B -m sentineldesk --home .demo integrations google-token --credentials-env {google_credentials_env} --token-env {google_token_env}",
            f"export {google_token_env}=\"$(cat .demo/secrets/google-token.json)\"",
        ],
        "sync_commands": [
            f".agent-venv/bin/python -B -m sentineldesk --home .demo email sync-gmail --account {account_id} --query \"deadline OR due\"",
            ".agent-venv/bin/python -B -m sentineldesk --home .demo integrations seed-calendar-draft",
            ".agent-venv/bin/python -B -m sentineldesk --home .demo calendar sync --destination google",
            ".agent-venv/bin/python -B -m sentineldesk --home .demo calendar sync --destination google --confirm --confirmation-id live-google-sandbox-001",
            ".agent-venv/bin/python -B -m sentineldesk --home .demo calendar sync --destination apple",
            ".agent-venv/bin/python -B -m sentineldesk --home .demo calendar sync --destination apple --confirm --confirmation-id live-apple-sandbox-001",
            f".agent-venv/bin/python -B -m sentineldesk --home .demo connectors state",
            f".agent-venv/bin/python -B -m sentineldesk --home .demo integrations reports",
            f".agent-venv/bin/python -B -m sentineldesk --home .demo integrations package latest",
            f".agent-venv/bin/python -B -m sentineldesk --home .demo integrations completion-audit --account {account_id} --source-release-path /tmp/extracted-sentineldesk",
            ".agent-venv/bin/python -B -m sentineldesk --home .demo privacy audit",
        ],
        "expected_remaining_before_auth": [
            "Gmail and Google Calendar env secrets are missing until Google OAuth credentials/token JSON are provided.",
            "Apple Calendar env secrets are missing until Apple ID and app-specific password are provided.",
            "Gmail cursor remains missing until a real Gmail sync succeeds.",
            "Google/Apple Calendar sync evidence remains missing until confirmed non-sandbox calendar writes create approval records.",
        ],
    }


def _module_check(name: str, module_name: str) -> VerificationCheck:
    try:
        available = importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:
        available = False
    return VerificationCheck(
        name=name,
        status="ready" if available else "missing",
        detail=f"Optional module {module_name} is {'available' if available else 'missing'}.",
        metadata={"module": module_name, "available": available},
    )


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


def _latest_all_report(paths: Paths) -> dict[str, Any] | None:
    for record in db.list_integration_verifications(paths, limit=50):
        if record.get("suite") == "all":
            return record
    return None


def _latest_package_status(paths: Paths, latest_all: dict[str, Any] | None) -> dict[str, Any]:
    if not latest_all:
        return {
            "name": "final_redacted_package",
            "status": "missing",
            "detail": "No persisted all-suite integration verification report found.",
            "verification_id": "",
            "package_path": "",
        }
    verification_id = str(latest_all.get("verification_id") or "")
    package_path = paths.artifacts / "integrations" / f"{verification_id}.share.zip"
    package_ready = latest_all.get("status") == "ready" and package_path.exists()
    return {
        "name": "final_redacted_package",
        "status": "ready" if package_ready else "missing",
        "detail": "Latest all-suite ready report has a redacted package." if package_ready else "Run the final all-suite readiness check with --require-ready --package.",
        "verification_id": verification_id,
        "report_status": latest_all.get("status"),
        "package_path": str(package_path),
        "package_exists": package_path.exists(),
    }


def _redacted_output_privacy_status(paths: Paths) -> dict[str, Any]:
    audit = audit_redacted_artifacts(paths.artifacts)
    clean = audit.get("status") == "clean"
    return {
        "name": "redacted_output_privacy",
        "status": "ready" if clean else "missing",
        "detail": "Redacted share outputs passed privacy audit." if clean else "Redacted share outputs have privacy audit findings.",
        "audit_status": audit.get("status"),
        "scanned_count": audit.get("scanned_count", 0),
        "issue_count": audit.get("issue_count", 0),
        "issues": audit.get("issues", []),
    }


def _source_release_audit_status(source_release_path: Path) -> dict[str, Any]:
    audit = audit_project_tree(source_release_path)
    clean = audit.get("status") == "clean"
    return {
        "name": "source_release_audit",
        "status": "ready" if clean else "missing",
        "detail": (
            "Extracted source release passed the project-tree release audit."
            if clean
            else "Extract the final source release package and run privacy release-audit --require-clean."
        ),
        "source_release_path": "[REDACTED_PATH]" if source_release_path.is_absolute() else str(source_release_path),
        "audit_status": audit.get("status"),
        "scanned_files": audit.get("scanned_files", 0),
        "scanned_dirs": audit.get("scanned_dirs", 0),
        "issue_count": audit.get("issue_count", 0),
        "issues": audit.get("issues", []),
    }


def _safe_source_release_path_for_command(source_release_path: str) -> str:
    path = Path(source_release_path)
    if source_release_path == DEFAULT_SOURCE_RELEASE_PATH or not path.is_absolute():
        return source_release_path
    return "[SOURCE_RELEASE_PATH]"


def _completion_next_commands(account_id: str) -> list[str]:
    return [
        ".agent-venv/bin/python -B -m sentineldesk --home .demo integrations env-template --account " + account_id,
        ".agent-venv/bin/python -B -m sentineldesk --home .demo integrations google-token --credentials-env SENTINEL_GOOGLE_CREDENTIALS_JSON --token-env SENTINEL_GOOGLE_TOKEN_JSON",
        ".agent-venv/bin/python -B -m sentineldesk --home .demo email sync-gmail --account " + account_id + ' --query "deadline OR due"',
        ".agent-venv/bin/python -B -m sentineldesk --home .demo integrations seed-calendar-draft",
        ".agent-venv/bin/python -B -m sentineldesk --home .demo calendar sync --destination google --confirm --confirmation-id live-google-sandbox-001",
        ".agent-venv/bin/python -B -m sentineldesk --home .demo calendar sync --destination apple --confirm --confirmation-id live-apple-sandbox-001",
        ".agent-venv/bin/python -B -m sentineldesk --home .demo integrations check --suite all --account " + account_id + " --require-ready --package",
        ".agent-venv/bin/python -B -m sentineldesk --home .demo privacy release-package --source . --output /tmp/sentineldesk.release.zip",
        "python3 -B -m zipfile -e /tmp/sentineldesk.release.zip /tmp/extracted-sentineldesk",
        ".agent-venv/bin/python -B -m sentineldesk --home .demo privacy release-audit --path /tmp/extracted-sentineldesk --require-clean",
        ".agent-venv/bin/python -B -m sentineldesk --home .demo integrations completion-audit --account " + account_id + " --source-release-path /tmp/extracted-sentineldesk --require-ready",
        ".agent-venv/bin/python -B -m sentineldesk --home .demo privacy audit --require-clean",
    ]


def _readiness_action_plan(
    *,
    account_id: str,
    current_checks: list[dict[str, Any]],
    requirements: list[dict[str, Any]],
    google_credentials_env: str,
    google_token_env: str,
    apple_user_env: str,
    apple_password_env: str,
    source_release_path: str,
) -> list[dict[str, Any]]:
    missing_checks = [str(check.get("name") or "") for check in current_checks if check.get("status") != "ready"]
    requirement_status = {str(item.get("name") or ""): str(item.get("status") or "") for item in requirements}
    module_checks = [
        name
        for name in missing_checks
        if name.startswith("langgraph.")
        or ".googleapiclient" in name
        or ".oauth_credentials" in name
        or ".oauth_flow" in name
        or ".caldav" in name
    ]
    google_auth_checks = [
        name
        for name in missing_checks
        if name
        in {
            "gmail.credentials",
            "gmail.credentials_format",
            "gmail.token",
            "gmail.token_format",
            "gmail.token_scope",
            "google_calendar.credentials",
            "google_calendar.credentials_format",
            "google_calendar.token",
            "google_calendar.token_format",
            "google_calendar.token_scope",
        }
    ]
    apple_auth_checks = [
        name
        for name in missing_checks
        if name
        in {
            "apple_calendar.username",
            "apple_calendar.username_format",
            "apple_calendar.app_password",
            "apple_calendar.app_password_format",
        }
    ]

    def action(
        action_id: str,
        description: str,
        missing: list[str],
        commands: list[str],
        *,
        side_effect: str = "local_only",
        requires_user_approval: bool = False,
    ) -> dict[str, Any]:
        return {
            "id": action_id,
            "status": "missing" if missing else "ready",
            "description": description,
            "missing_checks": missing,
            "commands": commands,
            "side_effect": side_effect,
            "requires_user_approval": requires_user_approval,
        }

    final_package_missing = ["final_redacted_package"] if requirement_status.get("final_redacted_package") != "ready" else []
    privacy_missing = (
        ["redacted_output_privacy"]
        if final_package_missing or requirement_status.get("redacted_output_privacy") != "ready"
        else []
    )
    source_release_missing = ["source_release_audit"] if requirement_status.get("source_release_audit") != "ready" else []
    source_release_command_path = _safe_source_release_path_for_command(source_release_path)
    calendar_draft_missing = (
        ["calendar_draft"]
        if "google_calendar.sync_evidence" in missing_checks or "apple_calendar.sync_evidence" in missing_checks
        else []
    )

    return [
        action(
            "install_optional_dependencies",
            "Install local optional dependencies for Gmail, Calendar, and LangGraph checks.",
            module_checks,
            [
                "python3 -B -m venv .agent-venv",
                ".agent-venv/bin/python -m pip install -e '.[agent,integrations]'",
            ],
        ),
        action(
            "configure_google_oauth",
            "Provide redacted Google OAuth env refs and generate a local token with Gmail readonly plus Calendar events scopes.",
            google_auth_checks,
            [
                f"export {google_credentials_env}='{{\"installed\":...}}'",
                f".agent-venv/bin/python -B -m sentineldesk --home .demo integrations google-token --credentials-env {google_credentials_env} --token-env {google_token_env}",
                f"export {google_token_env}=\"$(cat .demo/secrets/google-token.json)\"",
            ],
            requires_user_approval=True,
        ),
        action(
            "configure_apple_calendar",
            "Provide Apple CalDAV username and app-specific password through env refs.",
            apple_auth_checks,
            [
                f"export {apple_user_env}='[APPLE_ID_USERNAME]'",
                f"export {apple_password_env}='[APPLE_APP_SPECIFIC_PASSWORD]'",
            ],
            requires_user_approval=True,
        ),
        action(
            "run_gmail_sync",
            "Run a user-approved Gmail readonly sync so readiness has a non-secret cursor and email evidence.",
            ["gmail.cursor"] if "gmail.cursor" in missing_checks else [],
            [
                f".agent-venv/bin/python -B -m sentineldesk --home .demo email sync-gmail --account {account_id} --query \"deadline OR due\" --credentials-env {google_credentials_env} --token-env {google_token_env}",
            ],
            side_effect="external_read",
            requires_user_approval=True,
        ),
        action(
            "prepare_calendar_draft",
            "Ensure a local deadline draft exists before trying confirmation-gated external calendar sync.",
            calendar_draft_missing,
            [
                ".agent-venv/bin/python -B -m sentineldesk --home .demo integrations seed-calendar-draft",
                ".agent-venv/bin/python -B -m sentineldesk --home .demo calendar sync --destination google",
                ".agent-venv/bin/python -B -m sentineldesk --home .demo calendar sync --destination apple",
            ],
        ),
        action(
            "confirm_google_calendar_sync",
            "After reviewing the draft, confirm one Google Calendar sandbox write to create live sync evidence.",
            ["google_calendar.sync_evidence"] if "google_calendar.sync_evidence" in missing_checks else [],
            [
                f".agent-venv/bin/python -B -m sentineldesk --home .demo calendar sync --destination google --account {account_id} --confirm --confirmation-id live-google-sandbox-001 --google-credentials-env {google_credentials_env} --google-token-env {google_token_env}",
            ],
            side_effect="external_calendar_write",
            requires_user_approval=True,
        ),
        action(
            "confirm_apple_calendar_sync",
            "After reviewing the draft, confirm one Apple Calendar sandbox write to create live sync evidence.",
            ["apple_calendar.sync_evidence"] if "apple_calendar.sync_evidence" in missing_checks else [],
            [
                f".agent-venv/bin/python -B -m sentineldesk --home .demo calendar sync --destination apple --account {account_id} --confirm --confirmation-id live-apple-sandbox-001 --apple-user-env {apple_user_env} --apple-password-env {apple_password_env}",
            ],
            side_effect="external_calendar_write",
            requires_user_approval=True,
        ),
        action(
            "write_final_redacted_package",
            "Persist the final all-suite readiness report and its redacted ZIP package.",
            final_package_missing,
            [
                f".agent-venv/bin/python -B -m sentineldesk --home .demo integrations check --suite all --account {account_id} --require-ready --package",
            ],
        ),
        action(
            "run_final_privacy_audit",
            "Scan redacted verification and share outputs before treating the live handoff as complete.",
            privacy_missing,
            [
                f".agent-venv/bin/python -B -m sentineldesk --home .demo integrations completion-audit --account {account_id} --source-release-path {source_release_command_path} --require-ready",
                ".agent-venv/bin/python -B -m sentineldesk --home .demo privacy audit --require-clean",
            ],
        ),
        action(
            "run_source_release_audit",
            "Create the final public source ZIP, extract it, and verify the extracted tree excludes local runtime artifacts.",
            source_release_missing,
            [
                ".agent-venv/bin/python -B -m sentineldesk --home .demo privacy release-package --source . --output /tmp/sentineldesk.release.zip",
                f"python3 -B -m zipfile -e /tmp/sentineldesk.release.zip {source_release_command_path}",
                f".agent-venv/bin/python -B -m sentineldesk --home .demo privacy release-audit --path {source_release_command_path} --require-clean",
            ],
        ),
    ]


def _unique_verification_id(paths: Paths, base: str) -> str:
    if not db.get_integration_verification(paths, base) and not _artifact_path(paths, base).exists():
        return base
    for counter in range(2, 10000):
        candidate = f"{base}-{counter}"
        if not db.get_integration_verification(paths, candidate) and not _artifact_path(paths, candidate).exists():
            return candidate
    raise RuntimeError(f"Unable to allocate unique verification id for {base}")


def _compact_id(timestamp: str) -> str:
    compact = "".join(ch for ch in timestamp if ch.isalnum())
    return compact or "sandbox"


class _SandboxGmailClient:
    scopes = (GMAIL_READONLY_SCOPE,)

    def __init__(self, *, account_id: str, message_id: str) -> None:
        self.account_id = account_id
        self.message_id = message_id

    def search_messages(self, query: str, since: str, limit: int) -> dict[str, object]:
        return {
            "cursor": f"sandbox-history-{self.message_id}",
            "raw_count": 1,
            "query": query,
            "since": since,
            "messages": [
                {
                    "id": self.message_id,
                    "thread_id": "sandbox-thread",
                    "from": "sandbox@example.com",
                    "subject": "Sandbox deadline",
                    "date": "2026-06-10",
                    "body": "Submit the sandbox form by July 15, 2026.",
                }
            ][:limit],
        }


class _SandboxCalendarClient:
    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        self.created: list[dict[str, object]] = []

    def create_event(self, calendar_id: str, event: DeadlineEvent) -> dict[str, str]:
        self.created.append({"calendar_id": calendar_id, "event_id": event.event_id})
        return {"id": self.event_id}
