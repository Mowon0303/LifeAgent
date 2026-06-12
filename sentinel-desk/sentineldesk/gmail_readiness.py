from __future__ import annotations

import base64
import importlib.util
import json
from typing import Any

from . import db
from .config import Paths
from .extract import utc_now
from .integrations.google_workspace import GMAIL_READONLY_SCOPE
from .secrets import env_secret, resolve_secret, secret_status


def build_gmail_readiness(
    paths: Paths,
    *,
    account_id: str = "default",
    credentials_env: str = "SENTINEL_GOOGLE_CREDENTIALS_JSON",
    token_env: str = "SENTINEL_GOOGLE_TOKEN_JSON",
) -> dict[str, Any]:
    """Build a local-only Gmail first-run checklist.

    The checklist intentionally avoids Gmail API calls. It only inspects local
    env presence/shape, optional dependency availability, connector metadata,
    and stored local email evidence.
    """
    db.init_db(paths)
    selected_state = _select_gmail_connector_state(paths, account_id=account_id)
    messages = db.list_email_messages(paths, limit=500)
    credentials_check = _credentials_format_check(credentials_env)
    token_check = _token_format_check(token_env)
    token_scope_check = _token_scope_check(token_env, (GMAIL_READONLY_SCOPE,))
    dependency_check = _dependency_check()
    cursor_check = _cursor_check(selected_state, account_id=account_id)
    evidence_check = _local_evidence_check(messages)
    checks = [
        _env_presence_check("gmail.credentials_env", credentials_env),
        credentials_check,
        _env_presence_check("gmail.token_env", token_env),
        token_check,
        token_scope_check,
        dependency_check,
        cursor_check,
        evidence_check,
    ]
    oauth_ready = all(
        check["status"] == "ready"
        for check in (credentials_check, token_check, token_scope_check)
    )
    has_cursor = cursor_check["status"] == "ready"
    has_local_evidence = evidence_check["status"] == "ready"
    status = _readiness_status(
        credentials_check=credentials_check,
        token_check=token_check,
        token_scope_check=token_scope_check,
        dependency_check=dependency_check,
        oauth_ready=oauth_ready,
        has_local_evidence=has_local_evidence,
        has_cursor=has_cursor,
    )
    return {
        "status": status,
        "generated_at": utc_now(),
        "mode": "gmail_first_readiness",
        "account_id": "[REDACTED_CONNECTOR_METADATA]" if account_id and account_id != "default" else account_id,
        "credentials_env": credentials_env,
        "token_env": token_env,
        "checks": checks,
        "oauth_ready": oauth_ready,
        "has_local_evidence": has_local_evidence,
        "has_cursor": has_cursor,
        "stored_message_count": len(messages),
        "latest_received_at": max((str(message.get("received_at") or "") for message in messages), default=""),
        "connector": _safe_connector_state(selected_state),
        "next_action": _next_action(
            status,
            credentials_check=credentials_check,
            token_check=token_check,
            token_scope_check=token_scope_check,
        ),
        "external_network": False,
        "external_writes_performed": False,
    }


def _readiness_status(
    *,
    credentials_check: dict[str, Any],
    token_check: dict[str, Any],
    token_scope_check: dict[str, Any],
    dependency_check: dict[str, Any],
    oauth_ready: bool,
    has_local_evidence: bool,
    has_cursor: bool,
) -> str:
    if any(check["status"] != "ready" for check in (credentials_check, token_check, token_scope_check)):
        return "needs_oauth"
    if dependency_check["status"] != "ready":
        return "needs_dependency"
    if oauth_ready and (not has_cursor or not has_local_evidence):
        return "needs_sync"
    return "ready"


def _next_action(
    status: str,
    *,
    credentials_check: dict[str, Any],
    token_check: dict[str, Any],
    token_scope_check: dict[str, Any],
) -> dict[str, str]:
    if status == "needs_dependency":
        return {
            "kind": "install_gmail_dependencies",
            "label": "Install Gmail optional dependencies",
            "command": 'python3 -m pip install -e ".[gmail]"',
            "side_effect": "local_dependency_install",
        }
    if status == "needs_oauth":
        if credentials_check["status"] != "ready":
            return {
                "kind": "configure_google_credentials",
                "label": "Configure the Google OAuth client JSON env var",
                "command": 'export SENTINEL_GOOGLE_CREDENTIALS_JSON="$(cat <oauth-client.json>)"',
                "side_effect": "local_shell_env_only",
            }
        token_issue = "refresh token" if token_check["status"] != "ready" else "Gmail readonly scope"
        return {
            "kind": "setup_gmail_oauth",
            "label": f"Generate a Google token with {token_issue}",
            "command": "sentineldesk integrations google-token --credentials-env SENTINEL_GOOGLE_CREDENTIALS_JSON --token-env SENTINEL_GOOGLE_TOKEN_JSON --scope gmail.readonly",
            "side_effect": "local_oauth_token_write",
        }
    if status == "needs_sync":
        return {
            "kind": "sync_gmail_readonly",
            "label": "Run the first readonly Gmail sync",
            "command": "sentineldesk daily run --sync-gmail --account <account>",
            "side_effect": "gmail_readonly_plus_local_db_write",
        }
    return {
        "kind": "review_tasks",
        "label": "Review extracted local tasks",
        "command": "sentineldesk tasks list --view all --sort priority --status new",
        "side_effect": "local_read",
    }


def _select_gmail_connector_state(paths: Paths, *, account_id: str) -> dict[str, Any] | None:
    exact = db.get_connector_state(paths, connector="gmail_api", account_id=account_id)
    if exact:
        return exact
    for state in db.list_connector_states(paths, limit=20):
        if state.get("connector") == "gmail_api":
            return state
    return None


def _env_presence_check(name: str, env_name: str) -> dict[str, Any]:
    status = secret_status(env_secret(env_name))
    return {
        "name": name,
        "status": "ready" if status["available"] else "missing",
        "detail": f"{env_name} is configured." if status["available"] else f"{env_name} is not configured.",
        "metadata": {
            "env": env_name,
            "available": bool(status["available"]),
            "secret": status["redacted"],
        },
    }


def _credentials_format_check(env_name: str) -> dict[str, Any]:
    parsed, error = _load_env_json(env_name)
    if parsed is None:
        return {
            "name": "gmail.credentials_format",
            "status": "missing" if error == "missing" else "invalid",
            "detail": "Google OAuth client JSON is not available." if error == "missing" else "Google OAuth client JSON is not parseable.",
            "metadata": {"env": env_name, "secret": env_secret(env_name).redacted, "json_parseable": False},
        }
    client_block_name = "installed" if isinstance(parsed.get("installed"), dict) else "web" if isinstance(parsed.get("web"), dict) else ""
    client_block = parsed.get(client_block_name) if client_block_name else {}
    valid = isinstance(client_block, dict) and bool(client_block.get("client_id")) and bool(client_block.get("client_secret"))
    return {
        "name": "gmail.credentials_format",
        "status": "ready" if valid else "invalid",
        "detail": "Google OAuth client JSON has a compatible local format." if valid else "Google OAuth client JSON should contain an installed/web client_id and client_secret.",
        "metadata": {
            "env": env_name,
            "secret": env_secret(env_name).redacted,
            "json_parseable": True,
            "client_type": client_block_name or "unknown",
            "has_client_id": bool(isinstance(client_block, dict) and client_block.get("client_id")),
            "has_client_secret": bool(isinstance(client_block, dict) and client_block.get("client_secret")),
        },
    }


def _token_format_check(env_name: str) -> dict[str, Any]:
    parsed, error = _load_env_json(env_name)
    if parsed is None:
        return {
            "name": "gmail.token_format",
            "status": "missing" if error == "missing" else "invalid",
            "detail": "Google token JSON is not available." if error == "missing" else "Google token JSON is not parseable.",
            "metadata": {"env": env_name, "secret": env_secret(env_name).redacted, "json_parseable": False},
        }
    valid = bool(parsed.get("refresh_token") or parsed.get("token"))
    return {
        "name": "gmail.token_format",
        "status": "ready" if valid else "invalid",
        "detail": "Google token JSON has a compatible local format." if valid else "Google token JSON should include a refresh_token or access token.",
        "metadata": {
            "env": env_name,
            "secret": env_secret(env_name).redacted,
            "json_parseable": True,
            "has_refresh_token": bool(parsed.get("refresh_token")),
            "has_access_token": bool(parsed.get("token")),
        },
    }


def _token_scope_check(env_name: str, required_scopes: tuple[str, ...]) -> dict[str, Any]:
    parsed, error = _load_env_json(env_name)
    if parsed is None:
        return {
            "name": "gmail.token_scope",
            "status": "missing" if error == "missing" else "invalid",
            "detail": "Google token scopes are not available." if error == "missing" else "Google token scopes could not be read.",
            "metadata": {
                "env": env_name,
                "secret": env_secret(env_name).redacted,
                "required_scopes": list(required_scopes),
                "scopes_present": [],
                "missing_scopes": list(required_scopes),
            },
        }
    scopes = _extract_token_scopes(parsed)
    missing = [scope for scope in required_scopes if scope not in scopes]
    return {
        "name": "gmail.token_scope",
        "status": "ready" if not missing else "missing",
        "detail": "Google token includes Gmail readonly scope." if not missing else "Google token is missing Gmail readonly scope.",
        "metadata": {
            "env": env_name,
            "secret": env_secret(env_name).redacted,
            "required_scopes": list(required_scopes),
            "scopes_present": scopes,
            "missing_scopes": missing,
        },
    }


def _dependency_check() -> dict[str, Any]:
    modules = ("googleapiclient.discovery", "google.oauth2.credentials", "google_auth_oauthlib.flow")
    missing = [module for module in modules if not _module_available(module)]
    return {
        "name": "gmail.dependencies",
        "status": "ready" if not missing else "missing",
        "detail": "Gmail optional dependencies are importable." if not missing else "Install the Gmail optional dependencies before a live sync.",
        "metadata": {"required_modules": list(modules), "missing_modules": missing},
    }


def _cursor_check(state: dict[str, Any] | None, *, account_id: str) -> dict[str, Any]:
    selected_account = str((state or {}).get("account_id") or account_id or "")
    return {
        "name": "gmail.cursor",
        "status": "ready" if state and state.get("cursor") else "missing",
        "detail": "Stored Gmail cursor found." if state and state.get("cursor") else "No stored Gmail cursor yet.",
        "metadata": {
            "account_id": _redacted_account_id(selected_account),
            "connector": "gmail_api",
            "has_cursor": bool(state and state.get("cursor")),
            "updated_at": str((state or {}).get("updated_at") or ""),
        },
    }


def _local_evidence_check(messages: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": "gmail.local_evidence",
        "status": "ready" if messages else "missing",
        "detail": "Stored local email evidence is available." if messages else "No stored local email evidence yet.",
        "metadata": {
            "stored_message_count": len(messages),
            "latest_received_at": max((str(message.get("received_at") or "") for message in messages), default=""),
        },
    }


def _safe_connector_state(state: dict[str, Any] | None) -> dict[str, Any]:
    if not state:
        return {"connector": "gmail_api", "account_id": "", "has_cursor": False, "scopes": [], "updated_at": ""}
    return {
        "connector": str(state.get("connector") or "gmail_api"),
        "account_id": "[REDACTED_CONNECTOR_METADATA]" if state.get("account_id") else "",
        "has_cursor": bool(state.get("cursor")),
        "scopes": list(state.get("scopes") or []),
        "updated_at": str(state.get("updated_at") or ""),
    }


def _module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _redacted_account_id(account_id: str) -> str:
    if not account_id:
        return ""
    return "" if account_id == "default" else "[REDACTED_CONNECTOR_METADATA]"


def _load_env_json(env_name: str) -> tuple[dict[str, Any] | None, str]:
    ref = env_secret(env_name)
    try:
        raw = resolve_secret(ref)
    except Exception:
        return None, "missing"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        try:
            parsed = json.loads(base64.b64decode(raw).decode("utf-8"))
        except Exception:
            return None, "invalid"
    if not isinstance(parsed, dict):
        return None, "invalid"
    return parsed, ""


def _extract_token_scopes(token_info: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("scopes", "scope", "granted_scopes", "grantedScopes"):
        value = token_info.get(key)
        if isinstance(value, str):
            values.extend(item.strip() for chunk in value.split(",") for item in chunk.split() if item.strip())
        elif isinstance(value, (list, tuple)):
            values.extend(str(item).strip() for item in value if str(item).strip())
    return list(dict.fromkeys(values))
