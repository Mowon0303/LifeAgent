from __future__ import annotations

import base64
import importlib
import json
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sentineldesk.integrations.google_workspace import CALENDAR_EVENTS_SCOPE, GMAIL_READONLY_SCOPE
from sentineldesk.secure_files import write_owner_only_text
from sentineldesk.secrets import SecretRef, SecretUnavailable, env_secret, resolve_secret


# Least privilege by default: a token is only granted Gmail *read* access unless
# the caller explicitly asks for calendar write. The Gmail-first rollout must not
# be able to acquire a write scope by omission — once a user consents to
# calendar.events, taking it back means redoing the whole consent flow.
DEFAULT_GOOGLE_SCOPES = (GMAIL_READONLY_SCOPE,)
CALENDAR_WRITE_SCOPES = (CALENDAR_EVENTS_SCOPE,)
GOOGLE_SCOPE_ALIASES = {
    "gmail.readonly": GMAIL_READONLY_SCOPE,
    "calendar.events": CALENDAR_EVENTS_SCOPE,
}


@dataclass(frozen=True)
class GoogleTokenWriteResult:
    output_path: str
    protection: dict[str, object]
    token_env: str
    token_env_ref: str
    export_hint: str
    scopes: tuple[str, ...]
    flow: str
    open_browser: bool
    port: int

    def to_dict(self) -> dict[str, object]:
        return {
            "output_path": self.output_path,
            "protection": dict(self.protection),
            "token_env": self.token_env,
            "token_env_ref": self.token_env_ref,
            "export_hint": self.export_hint,
            "scopes": list(self.scopes),
            "flow": self.flow,
            "open_browser": self.open_browser,
            "port": self.port,
            "privacy": "Token JSON was written to disk with owner-only permissions and is not printed.",
        }


def normalize_google_scopes(scope_names: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if not scope_names:
        return DEFAULT_GOOGLE_SCOPES
    scopes: list[str] = []
    for name in scope_names:
        scopes.append(GOOGLE_SCOPE_ALIASES.get(name, name))
    return tuple(dict.fromkeys(scopes))


def write_google_oauth_token(
    *,
    credentials_ref: SecretRef,
    output_path: Path,
    token_env: str = "SENTINEL_GOOGLE_TOKEN_JSON",
    scopes: tuple[str, ...] = DEFAULT_GOOGLE_SCOPES,
    port: int = 0,
    open_browser: bool = True,
    flow_factory: Any | None = None,
) -> GoogleTokenWriteResult:
    credentials_info = _load_secret_json(credentials_ref)
    flow_cls = flow_factory or _installed_app_flow()
    flow = flow_cls.from_client_config(credentials_info, scopes=list(scopes))
    credentials = flow.run_local_server(port=port, open_browser=open_browser)
    token_json = _credentials_to_json(credentials)

    # Fails closed: if owner-only access cannot be applied and verified on this
    # platform, the token file is removed rather than left readable.
    protection = write_owner_only_text(output_path, token_json)

    return GoogleTokenWriteResult(
        output_path=str(output_path),
        protection=protection.to_dict(),
        token_env=token_env,
        token_env_ref=env_secret(token_env).redacted,
        export_hint=_export_hint(token_env, output_path),
        scopes=scopes,
        flow="google_auth_oauthlib.flow.InstalledAppFlow.run_local_server",
        open_browser=open_browser,
        port=port,
    )


def _export_hint(token_env: str, output_path: Path) -> str:
    """A shell line the user can actually paste on their own platform."""
    if sys.platform.startswith("win"):
        return f'$env:{token_env} = Get-Content -Raw "{output_path}"'
    return f'export {token_env}="$(cat {shlex.quote(str(output_path))})"'


def _credentials_to_json(credentials: Any) -> str:
    if hasattr(credentials, "to_json"):
        return str(credentials.to_json())
    if hasattr(credentials, "to_dict"):
        return json.dumps(credentials.to_dict(), ensure_ascii=False)
    raise SecretUnavailable("Google OAuth flow returned credentials without to_json or to_dict.")


def _load_secret_json(ref: SecretRef) -> dict[str, Any]:
    raw = resolve_secret(ref)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            return json.loads(base64.b64decode(raw).decode("utf-8"))
        except Exception as exc:
            raise SecretUnavailable(f"Secret {ref.redacted} is not JSON or base64 JSON.") from exc


def _installed_app_flow() -> Any:
    try:
        module = importlib.import_module("google_auth_oauthlib.flow")
    except ImportError as exc:
        raise SecretUnavailable("Optional Google OAuth dependency missing: google-auth-oauthlib.") from exc
    flow_cls = getattr(module, "InstalledAppFlow", None)
    if flow_cls is None:
        raise SecretUnavailable("google_auth_oauthlib.flow.InstalledAppFlow is unavailable.")
    return flow_cls
