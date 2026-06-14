"""Completion audit: roll up live readiness + package/privacy/source-release gates,
render the human handoff checklist, and produce the readiness action plan."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from sentineldesk import db
from sentineldesk.config import Paths
from sentineldesk.privacy import audit_project_tree, audit_redacted_artifacts

from .models import DEFAULT_SOURCE_RELEASE_PATH
from .runner import run_verification


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
