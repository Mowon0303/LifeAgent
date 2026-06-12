from __future__ import annotations

from typing import Any

from . import db
from .config import Paths
from .extract import utc_now
from .integrations.google_workspace import GoogleIntegrationUnavailable
from .secrets import SecretUnavailable


GMAIL_FAILURE_ACTION = "email.connector.sync.failed"
GMAIL_SUCCESS_ACTION = "email.connector.sync"


def record_gmail_sync_failure(
    paths: Paths,
    *,
    error: Exception,
    account_id: str = "default",
    command: str,
    query: str,
    since: str,
    limit: int,
    credentials_env: str,
    token_env: str,
    actor: str = "system",
    created_at: str | None = None,
) -> dict[str, Any]:
    """Persist a redacted Gmail sync failure and return local diagnostics."""
    db.init_db(paths)
    timestamp = created_at or utc_now()
    classification = classify_gmail_sync_error(error)
    db.insert_audit_event(
        paths,
        action=GMAIL_FAILURE_ACTION,
        actor=actor,
        subject="gmail_api:[REDACTED_CONNECTOR_METADATA]",
        capability="email_read",
        side_effect="external_read_failed_local_audit",
        allowed=False,
        confirmation_id="",
        metadata={
            "connector": "gmail_api",
            "account_id": _redacted_account_id(account_id),
            "command": command,
            "category": classification["category"],
            "error_type": classification["error_type"],
            "detail": classification["detail"],
            "query_present": bool(query),
            "query_length": len(query or ""),
            "since_present": bool(since),
            "limit": int(limit),
            "credentials_env": credentials_env,
            "token_env": token_env,
            "external_network_attempted": True,
            "external_writes_performed": False,
            "raw_error_included": False,
        },
        created_at=timestamp,
    )
    return build_gmail_sync_diagnostics(paths, account_id=account_id)


def build_gmail_sync_diagnostics(
    paths: Paths,
    *,
    account_id: str = "default",
    limit: int = 20,
) -> dict[str, Any]:
    """Build a redacted, local-only summary of recent Gmail sync attempts."""
    db.init_db(paths)
    events = [
        event
        for event in db.list_audit_events(paths, limit=max(limit * 4, 50))
        if _is_gmail_sync_event(event)
    ]
    failures = [event for event in events if event.get("action") == GMAIL_FAILURE_ACTION]
    successes = [event for event in events if event.get("action") == GMAIL_SUCCESS_ACTION]
    latest_failure = _safe_failure_event(failures[0]) if failures else None
    latest_success = _safe_success_event(successes[0]) if successes else None
    status = _diagnostics_status(latest_failure=latest_failure, latest_success=latest_success)
    return {
        "status": status,
        "generated_at": utc_now(),
        "mode": "gmail_sync_diagnostics",
        "account_id": _redacted_account_id(account_id),
        "latest_failure": latest_failure,
        "latest_success": latest_success,
        "recent_failure_count": len(failures[:limit]),
        "recent_success_count": len(successes[:limit]),
        "next_action": _next_action(status, latest_failure=latest_failure),
        "external_network": False,
        "external_writes_performed": False,
    }


def classify_gmail_sync_error(error: Exception) -> dict[str, str]:
    error_type = type(error).__name__
    message = str(error).lower()
    category = "unknown"
    detail = "Gmail sync failed for an unknown local or provider-side reason."

    if isinstance(error, GoogleIntegrationUnavailable) or "optional google dependency missing" in message:
        category = "missing_dependency"
        detail = "Gmail optional dependencies are not installed in this environment."
    elif isinstance(error, SecretUnavailable) and "missing required environment secret" in message:
        category = "missing_secret"
        detail = "A required Google OAuth environment secret is missing."
    elif isinstance(error, SecretUnavailable) or "not json or base64 json" in message:
        category = "invalid_secret_json"
        detail = "A Google OAuth secret is present but is not valid JSON or base64 JSON."
    elif any(marker in message for marker in ("invalid_grant", "invalid client", "invalid_client", "unauthorized_client", "refresh token")):
        category = "oauth_token_rejected"
        detail = "Google rejected the OAuth token or client authorization."
    elif any(marker in message for marker in ("insufficient", "forbidden", "access denied", "access_denied", "403", "permission")):
        category = "permission_denied"
        detail = "Google denied Gmail API access; check the app test user and Gmail readonly scope."
    elif any(marker in message for marker in ("rate limit", "ratelimit", "quota", "429", "too many requests")):
        category = "rate_limited"
        detail = "Gmail API rate or quota limits blocked the sync attempt."
    elif any(marker in message for marker in ("timeout", "timed out", "connection", "network", "temporary failure", "ssl")):
        category = "network_error"
        detail = "A network or TLS problem interrupted the Gmail sync attempt."
    elif "httperror" in error_type.lower() or "googleapiclient" in message:
        category = "google_api_error"
        detail = "Gmail API returned an error that was not classified more specifically."

    return {"category": category, "error_type": error_type, "detail": detail}


def _is_gmail_sync_event(event: dict[str, Any]) -> bool:
    action = event.get("action")
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    return action in {GMAIL_FAILURE_ACTION, GMAIL_SUCCESS_ACTION} and metadata.get("connector") == "gmail_api"


def _safe_failure_event(event: dict[str, Any]) -> dict[str, Any]:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    return {
        "audit_id": int(event.get("id") or 0),
        "created_at": str(event.get("created_at") or ""),
        "category": str(metadata.get("category") or "unknown"),
        "error_type": str(metadata.get("error_type") or ""),
        "detail": str(metadata.get("detail") or ""),
        "command": str(metadata.get("command") or ""),
        "query_present": bool(metadata.get("query_present")),
        "query_length": int(metadata.get("query_length") or 0),
        "since_present": bool(metadata.get("since_present")),
        "limit": int(metadata.get("limit") or 0),
        "credentials_env": str(metadata.get("credentials_env") or ""),
        "token_env": str(metadata.get("token_env") or ""),
        "external_network_attempted": bool(metadata.get("external_network_attempted")),
        "external_writes_performed": False,
        "raw_error_included": False,
    }


def _safe_success_event(event: dict[str, Any]) -> dict[str, Any]:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    return {
        "audit_id": int(event.get("id") or 0),
        "created_at": str(event.get("created_at") or ""),
        "message_count": int(metadata.get("message_count") or 0),
        "cursor_saved": bool(metadata.get("cursor_saved")),
        "scopes": list(metadata.get("scopes") or []),
        "warnings": list(metadata.get("warnings") or []),
        "external_writes_performed": False,
    }


def _diagnostics_status(
    *,
    latest_failure: dict[str, Any] | None,
    latest_success: dict[str, Any] | None,
) -> str:
    if latest_failure and (
        not latest_success or str(latest_failure.get("created_at") or "") >= str(latest_success.get("created_at") or "")
    ):
        return "failed"
    if latest_success:
        return "ready"
    return "no_attempt"


def _next_action(status: str, *, latest_failure: dict[str, Any] | None) -> dict[str, str]:
    if status == "no_attempt":
        return {
            "kind": "run_gmail_sync",
            "label": "Run the first readonly Gmail sync",
            "command": "sentineldesk daily run --sync-gmail --account <account>",
            "side_effect": "gmail_readonly_plus_local_db_write",
        }
    if status == "ready":
        return {
            "kind": "review_tasks",
            "label": "Review extracted local tasks",
            "command": "sentineldesk tasks list --view all --sort priority --status new",
            "side_effect": "local_read",
        }
    category = str((latest_failure or {}).get("category") or "unknown")
    if category == "missing_dependency":
        return {
            "kind": "install_gmail_dependencies",
            "label": "Install Gmail optional dependencies",
            "command": 'python3 -m pip install -e ".[gmail]"',
            "side_effect": "local_dependency_install",
        }
    if category in {"missing_secret", "invalid_secret_json"}:
        return {
            "kind": "check_gmail_readiness",
            "label": "Inspect OAuth env/token readiness",
            "command": "sentineldesk integrations gmail-readiness --account <account>",
            "side_effect": "local_read",
        }
    if category in {"oauth_token_rejected", "permission_denied"}:
        return {
            "kind": "refresh_gmail_oauth",
            "label": "Regenerate the Gmail readonly token",
            "command": "sentineldesk integrations google-token --credentials-env SENTINEL_GOOGLE_CREDENTIALS_JSON --token-env SENTINEL_GOOGLE_TOKEN_JSON --scope gmail.readonly",
            "side_effect": "local_oauth_token_write",
        }
    if category in {"rate_limited", "network_error"}:
        return {
            "kind": "retry_gmail_sync",
            "label": "Retry the readonly Gmail sync after the transient issue clears",
            "command": "sentineldesk daily run --sync-gmail --account <account>",
            "side_effect": "gmail_readonly_plus_local_db_write",
        }
    return {
        "kind": "run_gmail_verification",
        "label": "Run the Gmail readiness report for more context",
        "command": "sentineldesk integrations check --suite gmail --account <account>",
        "side_effect": "local_report_write",
    }


def _redacted_account_id(account_id: str) -> str:
    if not account_id:
        return ""
    return "" if account_id == "default" else "[REDACTED_CONNECTOR_METADATA]"
