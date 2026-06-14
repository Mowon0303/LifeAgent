"""Redacted env-setup template for the live-integration verification flow."""

from __future__ import annotations

from typing import Any

from sentineldesk.secrets import env_secret, secret_status


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
