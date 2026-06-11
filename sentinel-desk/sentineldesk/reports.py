from __future__ import annotations

import html
import json
import zipfile
from pathlib import Path
from typing import Any

from .redact import redact


SECRET_KEYS = {
    "access_token",
    "api_key",
    "app_password",
    "authorization",
    "client_secret",
    "cookie",
    "credentials",
    "credentials_json",
    "id_token",
    "password",
    "refresh_token",
    "secret",
    "set_cookie",
    "token",
    "token_json",
}
ATTACHMENT_NAME_KEYS = {"attachment_name", "attachment_names", "file_name", "filename"}
INVITEE_KEYS = {"attendee", "attendees", "calendar_attendees", "calendar_invitees", "invitee", "invitees", "organizer"}
CONNECTOR_METADATA_KEYS = {
    "account_id",
    "cursor",
    "etag",
    "gmail_account",
    "history_id",
    "page_token",
    "resource_id",
    "sync_token",
    "watch_id",
}


def redact_data(value: Any) -> Any:
    return _redact_data(value)


def _redact_data(value: Any, *, key: str = "") -> Any:
    normalized_key = _normalize_key(key)
    if normalized_key in SECRET_KEYS:
        return _redacted_like(value, "[REDACTED_SECRET]")
    if normalized_key in ATTACHMENT_NAME_KEYS:
        return _redacted_like(value, "[REDACTED_ATTACHMENT]")
    if normalized_key in INVITEE_KEYS:
        return _redacted_like(value, "[REDACTED_INVITEE]")
    if normalized_key in CONNECTOR_METADATA_KEYS:
        return _redacted_like(value, "[REDACTED_CONNECTOR_METADATA]")
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_redact_data(item) for item in value]
    if isinstance(value, dict):
        return {item_key: _redact_data(item, key=item_key) for item_key, item in value.items()}
    return value


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _redacted_like(value: Any, marker: str) -> Any:
    if isinstance(value, list):
        return [marker for _ in value]
    if isinstance(value, tuple):
        return [marker for _ in value]
    if isinstance(value, dict):
        return marker
    if value is None:
        return None
    return marker


def evidence_report_html(evidence: dict[str, Any]) -> str:
    redacted = redact_data(evidence)
    alert = redacted.get("alert", {})
    status = redacted.get("status", {})
    health = redacted.get("health", {})
    deadlines = redacted.get("deadlines", [])
    diff = "\n".join(str(line) for line in redacted.get("diff_preview", []))
    after_preview = str(redacted.get("after_text_preview", ""))
    before_preview = str(redacted.get("before_text_preview", ""))
    deadline_rows = "\n".join(
        f"<tr><td>{html.escape(str(item.get('date_text', '')))}</td><td>{html.escape(str(item.get('confidence', '')))}</td><td>{html.escape(str(item.get('context', '')))}</td></tr>"
        for item in deadlines
        if isinstance(item, dict)
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SentinelDesk Evidence Report</title>
  <style>
    body {{ margin: 32px; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #20231f; }}
    h1 {{ font-size: 24px; margin: 0 0 8px; letter-spacing: 0; }}
    h2 {{ font-size: 16px; margin-top: 24px; }}
    .meta {{ color: #656b5e; font-size: 13px; margin-bottom: 20px; }}
    .grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
    .box {{ border: 1px solid #d9ddd2; border-radius: 8px; padding: 12px; }}
    .level {{ font-weight: 750; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #111; color: #f4f4ef; padding: 12px; border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; vertical-align: top; border-bottom: 1px solid #d9ddd2; padding: 8px; font-size: 13px; }}
  </style>
</head>
<body>
  <h1>SentinelDesk Evidence Report</h1>
  <div class="meta">{html.escape(str(redacted.get("target_name", "")))} · {html.escape(str(redacted.get("captured_at", "")))}</div>
  <div class="grid">
    <div class="box"><strong>Alert</strong><br><span class="level">{html.escape(str(alert.get("level", "")))}</span><br>{html.escape(str(alert.get("reason", "")))}</div>
    <div class="box"><strong>Status</strong><br>{html.escape(str(status.get("value", "")))}<br>{html.escape(str(status.get("evidence", "")))}</div>
    <div class="box"><strong>Health</strong><br>{html.escape(str(health.get("state", "")))}<br>{html.escape(", ".join(str(item) for item in health.get("reasons", [])))}</div>
  </div>
  <h2>Deadlines</h2>
  <table><thead><tr><th>Date</th><th>Confidence</th><th>Context</th></tr></thead><tbody>{deadline_rows}</tbody></table>
  <h2>Diff Preview</h2>
  <pre>{html.escape(diff)}</pre>
  <h2>Before Preview</h2>
  <pre>{html.escape(before_preview)}</pre>
  <h2>After Preview</h2>
  <pre>{html.escape(after_preview)}</pre>
</body>
</html>
"""


def write_report(path: Path, evidence: dict[str, Any]) -> None:
    path.write_text(evidence_report_html(evidence), encoding="utf-8")


def write_redacted_json(path: Path, evidence: dict[str, Any]) -> None:
    path.write_text(json.dumps(redact_data(evidence), ensure_ascii=False, indent=2), encoding="utf-8")


def package_path_for(evidence_path: Path) -> Path:
    name = evidence_path.name
    if name.endswith(".evidence.json"):
        return evidence_path.with_name(name.removesuffix(".evidence.json") + ".share.zip")
    return evidence_path.with_suffix(".share.zip")


def package_manifest(redacted: dict[str, Any]) -> dict[str, Any]:
    alert = redacted.get("alert", {}) if isinstance(redacted.get("alert"), dict) else {}
    status = redacted.get("status", {}) if isinstance(redacted.get("status"), dict) else {}
    health = redacted.get("health", {}) if isinstance(redacted.get("health"), dict) else {}
    return {
        "package_format": "sentineldesk-redacted-evidence-v1",
        "target_name": redacted.get("target_name"),
        "target_kind": redacted.get("target_kind"),
        "captured_at": redacted.get("captured_at"),
        "alert_level": alert.get("level"),
        "alert_reason": alert.get("reason"),
        "status_value": status.get("value"),
        "health_state": health.get("state"),
        "files": [
            "README.md",
            "manifest.json",
            "evidence.redacted.json",
            "report.html",
        ],
        "privacy": "Contains only redacted SentinelDesk evidence. Raw portal URLs, local file URLs, cookies, screenshots, DOM dumps, and databases are intentionally excluded.",
    }


def package_readme(redacted: dict[str, Any]) -> str:
    manifest = package_manifest(redacted)
    return f"""# SentinelDesk Redacted Evidence Package

This package is intended for portfolio or review sharing.

## Summary

- Target: {manifest.get("target_name") or ""}
- Kind: {manifest.get("target_kind") or ""}
- Captured at: {manifest.get("captured_at") or ""}
- Alert: {manifest.get("alert_level") or ""} - {manifest.get("alert_reason") or ""}
- Status: {manifest.get("status_value") or ""}
- Health: {manifest.get("health_state") or ""}

## Files

- `report.html`: readable redacted evidence report.
- `evidence.redacted.json`: structured privacy-safe evidence bundle.
- `manifest.json`: package metadata.

## Privacy Boundary

Raw portal URLs, local file URLs, cookies, screenshots, DOM dumps, traces, and local databases are not included.
"""


def write_evidence_package(package_path: Path, evidence: dict[str, Any]) -> Path:
    redacted = redact_data(evidence)
    package_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.md", package_readme(redacted))
        archive.writestr("manifest.json", json.dumps(package_manifest(redacted), ensure_ascii=False, indent=2))
        archive.writestr("evidence.redacted.json", json.dumps(redacted, ensure_ascii=False, indent=2))
        archive.writestr("report.html", evidence_report_html(redacted))
    return package_path


def integration_report_html(report: dict[str, Any]) -> str:
    redacted = redact_data(report)
    checks = redacted.get("checks", [])
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('name', '')))}</td>"
        f"<td>{html.escape(str(item.get('status', '')))}</td>"
        f"<td>{html.escape(str(item.get('detail', '')))}</td>"
        f"<td><pre>{html.escape(json.dumps(item.get('metadata', {}), ensure_ascii=False, indent=2))}</pre></td>"
        "</tr>"
        for item in checks
        if isinstance(item, dict)
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SentinelDesk Integration Verification</title>
  <style>
    body {{ margin: 32px; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #20231f; }}
    h1 {{ font-size: 24px; margin: 0 0 8px; letter-spacing: 0; }}
    .meta {{ color: #656b5e; font-size: 13px; margin-bottom: 20px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; vertical-align: top; border-bottom: 1px solid #d9ddd2; padding: 8px; font-size: 13px; }}
    pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 12px; }}
  </style>
</head>
<body>
  <h1>SentinelDesk Integration Verification</h1>
  <div class="meta">ID: {html.escape(str(redacted.get("verification_id", "")))} · Suite: {html.escape(str(redacted.get("suite", "")))} · Status: {html.escape(str(redacted.get("status", "")))} · Created: {html.escape(str(redacted.get("created_at", "")))}</div>
  <table><thead><tr><th>Check</th><th>Status</th><th>Detail</th><th>Metadata</th></tr></thead><tbody>{rows}</tbody></table>
</body>
</html>
"""


def integration_package_manifest(redacted: dict[str, Any]) -> dict[str, Any]:
    return {
        "package_format": "sentineldesk-redacted-integration-verification-v1",
        "verification_id": redacted.get("verification_id"),
        "suite": redacted.get("suite"),
        "status": redacted.get("status"),
        "created_at": redacted.get("created_at"),
        "check_count": len(redacted.get("checks", [])) if isinstance(redacted.get("checks"), list) else 0,
        "files": [
            "README.md",
            "manifest.json",
            "verification.redacted.json",
            "report.html",
        ],
        "privacy": "Contains only redacted integration verification evidence. Secret values, local paths, account identifiers, and connector cursors are intentionally redacted.",
    }


def integration_package_readme(redacted: dict[str, Any]) -> str:
    manifest = integration_package_manifest(redacted)
    return f"""# SentinelDesk Redacted Integration Verification

This package is intended for internal review of live/sandbox integration readiness.

## Summary

- Verification ID: {manifest.get("verification_id") or ""}
- Suite: {manifest.get("suite") or ""}
- Status: {manifest.get("status") or ""}
- Created at: {manifest.get("created_at") or ""}
- Check count: {manifest.get("check_count") or 0}

## Files

- `report.html`: readable redacted verification report.
- `verification.redacted.json`: structured privacy-safe verification data.
- `manifest.json`: package metadata.

## Privacy Boundary

Secret values, local paths, account identifiers, connector cursors, tokens, app passwords, and raw credential JSON are not included.
"""


def integration_package_path_for(report: dict[str, Any], artifacts_root: Path) -> Path:
    verification_id = str(report.get("verification_id") or "integration-verification")
    return artifacts_root / "integrations" / f"{verification_id}.share.zip"


def write_integration_verification_package(package_path: Path, report: dict[str, Any]) -> Path:
    redacted = redact_data(report)
    package_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.md", integration_package_readme(redacted))
        archive.writestr("manifest.json", json.dumps(integration_package_manifest(redacted), ensure_ascii=False, indent=2))
        archive.writestr("verification.redacted.json", json.dumps(redacted, ensure_ascii=False, indent=2))
        archive.writestr("report.html", integration_report_html(redacted))
    return package_path
