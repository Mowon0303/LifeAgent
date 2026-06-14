"""Route handlers for portal targets, runs, scenarios, and evidence artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from .. import db
from ..monitor import run_all
from ..reports import package_path_for, redact_data, write_evidence_package
from ..scenarios import apply_scenario, list_scenarios

if TYPE_CHECKING:  # pragma: no cover - typing only
    from urllib.parse import ParseResult

    from .app import Handler


def handle_targets(h: "Handler", parsed: "ParseResult") -> None:
    h.send_json(db.list_targets(h.paths))


def handle_runs(h: "Handler", parsed: "ParseResult") -> None:
    h.send_json(db.list_runs(h.paths, limit=100))


def handle_alerts(h: "Handler", parsed: "ParseResult") -> None:
    h.send_json(db.list_alerts(h.paths, limit=100))


def handle_scenarios(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    h.send_json(list_scenarios(kind=query.get("kind", [None])[0]))


def handle_evidence(h: "Handler", parsed: "ParseResult") -> None:
    run_id = parsed.path.rsplit("/", 1)[-1]
    run = db.get_run(h.paths, run_id)
    if not run:
        h.send_json({"error": "not found"}, status=404)
        return
    evidence_path = Path(run["evidence"]["path"])
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    query = parse_qs(parsed.query)
    h.send_json(redact_data(evidence) if query.get("redacted", ["0"])[0] in {"1", "true", "yes"} else evidence)


def handle_report(h: "Handler", parsed: "ParseResult") -> None:
    run_id = parsed.path.rsplit("/", 1)[-1]
    run = db.get_run(h.paths, run_id)
    if not run:
        h.send_json({"error": "not found"}, status=404)
        return
    report_path = Path(run["evidence"].get("report_path", ""))
    if not report_path.exists():
        h.send_json({"error": "report not found"}, status=404)
        return
    h.send_text(report_path.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8")


def handle_package(h: "Handler", parsed: "ParseResult") -> None:
    run_id = parsed.path.rsplit("/", 1)[-1]
    run = db.get_run(h.paths, run_id)
    if not run:
        h.send_json({"error": "not found"}, status=404)
        return
    evidence_path = Path(run["evidence"]["path"])
    if not evidence_path.exists():
        h.send_json({"error": "evidence not found"}, status=404)
        return
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    package_path = write_evidence_package(package_path_for(evidence_path), evidence)
    h.send_file(
        package_path,
        content_type="application/zip",
        download_name=package_path.name,
    )


def handle_traces(h: "Handler", parsed: "ParseResult") -> None:
    run_id = parsed.path.rsplit("/", 1)[-1]
    h.send_json(db.list_traces(h.paths, run_id))


def handle_run(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    name = query.get("name", [None])[0]
    try:
        h.send_json(run_all(h.paths, name=name))
    except Exception as error:  # noqa: BLE001 - fail-soft API surface
        h.send_json({"error": str(error)}, status=500)


def handle_scenario(h: "Handler", parsed: "ParseResult") -> None:
    query = parse_qs(parsed.query)
    scenario_id = query.get("scenario", [None])[0]
    target_name = query.get("target", [None])[0]
    run_after_apply = query.get("run", ["0"])[0] in {"1", "true", "yes"}
    if not scenario_id:
        h.send_json({"error": "scenario query parameter required"}, status=400)
        return
    try:
        target = apply_scenario(h.paths, scenario_id, target_name=target_name)
        runs = run_all(h.paths, name=target["name"]) if run_after_apply else []
        h.send_json({"target": target, "runs": runs})
    except Exception as error:  # noqa: BLE001 - fail-soft API surface
        h.send_json({"error": str(error)}, status=500)
