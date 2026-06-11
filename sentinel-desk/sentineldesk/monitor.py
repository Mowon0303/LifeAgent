from __future__ import annotations

import difflib
import json
import re
import urllib.request
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from . import db
from .cdp import capture_from_url
from .config import Paths
from .extract import Extraction, extract_page, utc_now
from .policy import VerticalPolicy, load_policy, policy_for_kind
from .reports import write_redacted_json, write_report


@dataclass(frozen=True)
class Capture:
    html: str
    final_url: str
    screenshot: bytes | None = None


def fetch_url(url: str) -> Capture:
    parsed = urlparse(url)
    if parsed.scheme == "cdp":
        capture = capture_from_url(url)
        return Capture(html=capture.html, final_url=capture.final_url, screenshot=capture.screenshot)
    if parsed.scheme == "file":
        path = Path(urllib.request.url2pathname(parsed.path))
        return Capture(html=path.read_text(encoding="utf-8", errors="replace"), final_url=url)
    request = urllib.request.Request(url, headers={"User-Agent": "SentinelDesk/0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return Capture(html=response.read().decode("utf-8", errors="replace"), final_url=response.geturl())


def read_artifact(path: str | None) -> str:
    if not path:
        return ""
    file_path = Path(path)
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8", errors="replace")


def deadline_set(deadlines: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("date_text", "")).lower() for item in deadlines if item.get("date_text")}


def summarize_diff(before: str, after: str, limit: int = 24) -> list[str]:
    before_lines = before.splitlines() or [before]
    after_lines = after.splitlines() or [after]
    diff = list(difflib.unified_diff(before_lines, after_lines, fromfile="before", tofile="after", lineterm=""))
    return diff[:limit]


def classify_run(
    previous: dict[str, Any] | None,
    extraction: Extraction,
    high_stakes: bool,
    *,
    kind: str = "generic",
    policy: VerticalPolicy | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    active_policy = policy or policy_for_kind(kind, high_stakes=high_stakes)
    health = extraction.health
    status = extraction.status
    deadlines = extraction.deadlines

    if health["state"] != "ok":
        return (
            {"changed": True, "kind": "uncertain_health", "status_changed": False, "deadline_changed": False},
            {
                "level": "uncertain",
                "reason": "Cannot verify portal state: " + "; ".join(health["reasons"]),
                "confidence": health["confidence"],
                "fail_loud": True,
            },
        )

    if status["value"] == "unknown" and active_policy.fail_on_unknown_status:
        return (
            {"changed": True, "kind": "unknown_status", "status_changed": False, "deadline_changed": False},
            {
                "level": "uncertain",
                "reason": active_policy.unknown_status_reason,
                "confidence": status["confidence"],
                "fail_loud": True,
            },
        )

    if previous is None:
        return (
            {"changed": False, "kind": "baseline", "status_changed": False, "deadline_changed": False},
            {
                "level": "baseline",
                "reason": "First verified snapshot stored as baseline.",
                "confidence": min(health["confidence"], status["confidence"]),
                "fail_loud": False,
            },
        )

    previous_status = previous.get("status", {}).get("value", "unknown")
    previous_deadlines = deadline_set(previous.get("deadlines", []))
    current_deadlines = deadline_set(deadlines)
    status_changed = previous_status != status["value"]
    deadline_changed = previous_deadlines != current_deadlines
    text_changed = previous.get("text_hash") != extraction.text_hash

    if status_changed or deadline_changed:
        parts = []
        if status_changed:
            parts.append(f"status changed from {previous_status} to {status['value']}")
        if deadline_changed:
            parts.append("deadline candidates changed")
        return (
            {
                "changed": True,
                "kind": "meaningful_change",
                "status_changed": status_changed,
                "deadline_changed": deadline_changed,
            },
            {
                "level": active_policy.meaningful_change_level,
                "reason": "; ".join(parts),
                "confidence": 0.88,
                "fail_loud": False,
            },
        )

    if text_changed:
        return (
            {"changed": True, "kind": "irrelevant_or_unclassified_change", "status_changed": False, "deadline_changed": False},
            {
                "level": active_policy.text_change_level,
                "reason": "Page text changed, but status and deadline candidates did not change.",
                "confidence": 0.62,
                "fail_loud": False,
            },
        )

    return (
        {"changed": False, "kind": "no_change", "status_changed": False, "deadline_changed": False},
        {"level": "none", "reason": "No text/status/deadline change detected.", "confidence": 0.91, "fail_loud": False},
    )


def evidence_bundle(
    *,
    target: dict[str, Any],
    previous: dict[str, Any] | None,
    extraction: Extraction,
    alert: dict[str, Any],
    captured_at: str,
) -> dict[str, Any]:
    before_text = read_artifact(previous.get("text_path") if previous else None)
    after_text = extraction.text
    return {
        "target_name": target["name"],
        "target_url": target["url"],
        "target_kind": target.get("kind", "generic"),
        "captured_at": captured_at,
        "status": extraction.status,
        "deadlines": extraction.deadlines,
        "health": extraction.health,
        "alert": alert,
        "before_run_id": previous.get("run_id") if previous else None,
        "before_text_preview": before_text[:1000],
        "after_text_preview": after_text[:1000],
        "diff_preview": summarize_diff(before_text, after_text) if previous else [],
    }


def run_target(paths: Paths, target: dict[str, Any]) -> dict[str, Any]:
    run_id = uuid4().hex[:12]
    captured_at = utc_now()
    target_dir = paths.artifacts / re.sub(r"[^a-zA-Z0-9_.-]+", "-", target["name"]).strip("-")
    target_dir.mkdir(parents=True, exist_ok=True)

    db.insert_trace(paths, run_id=run_id, stage="capture_start", input_summary=target["url"], output_summary="pending", created_at=captured_at)
    capture_error = ""
    try:
        capture = fetch_url(target["url"])
        extraction = extract_page(capture.html)
    except Exception as error:
        capture_error = f"{type(error).__name__}: {error}"
        capture = Capture(
            html=f"<!doctype html><html><head><title>Capture failed</title></head><body><h1>Capture failed</h1><p>{capture_error}</p></body></html>",
            final_url=target["url"],
        )
        extraction = replace(
            extract_page(capture.html),
            health={"state": "uncertain", "reasons": [f"capture_error: {capture_error}"], "confidence": 0.15},
        )
    previous = db.latest_run(paths, int(target["id"]))
    policy = load_policy(paths, target.get("kind", "generic"), high_stakes=bool(target.get("high_stakes", 1)))
    diff, alert = classify_run(previous, extraction, bool(target.get("high_stakes", 1)), kind=target.get("kind", "generic"), policy=policy)

    html_path = target_dir / f"{run_id}.html"
    text_path = target_dir / f"{run_id}.txt"
    screenshot_path = target_dir / f"{run_id}.png" if capture.screenshot is not None else None
    evidence_path = target_dir / f"{run_id}.evidence.json"
    redacted_path = target_dir / f"{run_id}.redacted.json"
    report_path = target_dir / f"{run_id}.report.html"
    html_path.write_text(capture.html, encoding="utf-8")
    text_path.write_text(extraction.text, encoding="utf-8")
    if screenshot_path:
        screenshot_path.write_bytes(capture.screenshot or b"")
    evidence = evidence_bundle(target=target, previous=previous, extraction=extraction, alert=alert, captured_at=captured_at)
    evidence["artifacts"] = {
        "html_path": str(html_path),
        "text_path": str(text_path),
        "screenshot_path": str(screenshot_path) if screenshot_path else None,
    }
    if capture_error:
        evidence["capture_error"] = capture_error
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    write_redacted_json(redacted_path, evidence)
    write_report(report_path, evidence)

    run = {
        "run_id": run_id,
        "target_id": int(target["id"]),
        "captured_at": captured_at,
        "final_url": capture.final_url,
        "title": extraction.title,
        "text_hash": extraction.text_hash,
        "text_path": text_path,
        "html_path": html_path,
        "screenshot_path": str(screenshot_path) if screenshot_path else None,
        "health": extraction.health,
        "status": extraction.status,
        "deadlines": extraction.deadlines,
        "diff": diff,
        "alert": alert,
        "policy": asdict(policy),
        "evidence": {
            "path": str(evidence_path),
            "redacted_path": str(redacted_path),
            "report_path": str(report_path),
            "preview": evidence["after_text_preview"][:280],
        },
    }
    db.insert_run(paths, run)
    db.insert_trace(paths, run_id=run_id, stage="extract", input_summary=capture.final_url, output_summary=extraction.status["value"], created_at=captured_at)
    db.insert_trace(paths, run_id=run_id, stage="classify", input_summary=diff["kind"], output_summary=alert["level"], created_at=captured_at)
    return run


def run_all(paths: Paths, name: str | None = None) -> list[dict[str, Any]]:
    if name:
        target = db.get_target(paths, name=name)
        if not target:
            raise ValueError(f"No target named {name!r}")
        return [run_target(paths, target)]
    return [run_target(paths, target) for target in db.list_targets(paths) if target.get("enabled")]
