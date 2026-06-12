from __future__ import annotations

from typing import Any

from . import db
from .config import Paths
from .email.connectors import EmailSyncRequest, GmailApiEmailConnector
from .email.ingest import sync_connector
from .integrations.google_workspace import GMAIL_READONLY_SCOPE, GoogleOAuthConfig, GoogleWorkspaceFactory
from .secrets import env_secret


DEFAULT_DAILY_GMAIL_QUERY = "deadline OR due OR payment OR notice OR required OR action"


def run_gmail_readonly_sync(
    paths: Paths,
    *,
    account_id: str = "default",
    query: str = "",
    default_query: str = "",
    since: str | None = None,
    limit: int = 50,
    credentials_env: str = "SENTINEL_GOOGLE_CREDENTIALS_JSON",
    token_env: str = "SENTINEL_GOOGLE_TOKEN_JSON",
) -> dict[str, Any]:
    """Run the explicit readonly Gmail sync and return the raw local summary.

    The caller owns redaction before exposing this payload to UI surfaces.
    """
    db.init_db(paths)
    state = db.get_connector_state(paths, connector="gmail_api", account_id=account_id)
    resolved_since = since if since is not None else str((state or {}).get("cursor") or "")
    resolved_query = query or default_query
    config = GoogleOAuthConfig(
        credentials_json=env_secret(credentials_env),
        token_json=env_secret(token_env),
        scopes=(GMAIL_READONLY_SCOPE,),
        account_id=account_id,
    )
    client = GoogleWorkspaceFactory(config).gmail_client()
    setattr(client, "account_id", account_id)
    setattr(client, "scopes", config.scopes)
    summary = sync_connector(
        paths,
        GmailApiEmailConnector(client),
        EmailSyncRequest(query=resolved_query, since=resolved_since, limit=limit),
        account_id=account_id,
    )
    return {
        "mode": "gmail_readonly",
        "external_network": True,
        "query": resolved_query,
        "since": resolved_since,
        "oauth": config.safe_summary(),
        **summary,
    }
