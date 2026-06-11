from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .config import Paths


@dataclass(frozen=True)
class VerticalPolicy:
    kind: str
    label: str
    fail_on_unknown_status: bool
    meaningful_change_level: str
    text_change_level: str
    unknown_status_reason: str
    high_stakes_default: bool = True


BASE_POLICIES: dict[str, VerticalPolicy] = {
    "generic": VerticalPolicy(
        kind="generic",
        label="High-stakes portal",
        fail_on_unknown_status=True,
        meaningful_change_level="critical",
        text_change_level="info",
        unknown_status_reason="High-stakes page was readable, but no known status marker was found.",
    ),
    "opt": VerticalPolicy(
        kind="opt",
        label="OPT/USCIS/OIS",
        fail_on_unknown_status=True,
        meaningful_change_level="critical",
        text_change_level="info",
        unknown_status_reason="OPT/USCIS/OIS page was readable, but no known case-status marker was found.",
    ),
    "appointment": VerticalPolicy(
        kind="appointment",
        label="Appointment slot",
        fail_on_unknown_status=True,
        meaningful_change_level="critical",
        text_change_level="info",
        unknown_status_reason="Appointment page was readable, but no slot/status marker was found.",
    ),
    "lease": VerticalPolicy(
        kind="lease",
        label="Lease/rent deadline",
        fail_on_unknown_status=True,
        meaningful_change_level="critical",
        text_change_level="info",
        unknown_status_reason="Lease portal was readable, but no rent/deadline status marker was found.",
    ),
    "job": VerticalPolicy(
        kind="job",
        label="Job application",
        fail_on_unknown_status=False,
        meaningful_change_level="warning",
        text_change_level="info",
        unknown_status_reason="Job page status marker was not found.",
    ),
}

ALIASES = {
    "uscis": "opt",
    "ois": "opt",
    "visa": "appointment",
}


def normalize_kind(kind: str | None) -> str:
    value = (kind or "generic").strip().lower()
    return ALIASES.get(value, value)


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    return fallback


def _str(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def policy_from_config(base: VerticalPolicy, config: dict[str, Any]) -> VerticalPolicy:
    vertical = config.get("vertical", {})
    override = vertical.get(base.kind, {}) if isinstance(vertical, dict) else {}
    if not isinstance(override, dict):
        return base
    return replace(
        base,
        label=_str(override.get("label"), base.label),
        fail_on_unknown_status=_bool(override.get("fail_on_unknown_status"), base.fail_on_unknown_status),
        meaningful_change_level=_str(override.get("meaningful_change_level"), base.meaningful_change_level),
        text_change_level=_str(override.get("text_change_level"), base.text_change_level),
        unknown_status_reason=_str(override.get("unknown_status_reason"), base.unknown_status_reason),
        high_stakes_default=_bool(override.get("high_stakes_default"), base.high_stakes_default),
    )


def policy_for_kind(kind: str | None, *, high_stakes: bool = True, config: dict[str, Any] | None = None) -> VerticalPolicy:
    normalized = normalize_kind(kind)
    base = BASE_POLICIES.get(normalized, BASE_POLICIES["generic"])
    policy = policy_from_config(base, config or {})
    if not high_stakes:
        return replace(policy, fail_on_unknown_status=False, meaningful_change_level="warning")
    return policy


def load_policy(paths: Paths, kind: str | None, *, high_stakes: bool = True) -> VerticalPolicy:
    return policy_for_kind(kind, high_stakes=high_stakes, config=load_config(paths.config))


def list_policies(paths: Paths | None = None) -> list[dict[str, Any]]:
    config = load_config(paths.config) if paths else {}
    return [
        policy_from_config(policy, config).__dict__
        for key, policy in sorted(BASE_POLICIES.items())
        if key != "job"
    ]
