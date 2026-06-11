from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from . import db
from .config import Paths, ensure_dirs, file_url, seed_demo_fixtures
from .extract import utc_now


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str
    kind: str
    fixture: str
    target_name: str
    expected_alert: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="opt_baseline",
        label="OPT baseline submitted",
        kind="opt",
        fixture="opt_submitted.html",
        target_name="Demo OPT Case",
        expected_alert="baseline",
        description="Readable OPT case page with submitted/pending status and a known response deadline.",
    ),
    Scenario(
        id="opt_action_required",
        label="OPT action required",
        kind="opt",
        fixture="opt_action_required.html",
        target_name="Demo OPT Case",
        expected_alert="critical",
        description="OPT case changes to request-for-evidence with an earlier response deadline.",
    ),
    Scenario(
        id="opt_approved",
        label="OPT approved",
        kind="opt",
        fixture="opt_approved.html",
        target_name="Demo OPT Case",
        expected_alert="critical",
        description="OPT case changes to approved/card-produced status.",
    ),
    Scenario(
        id="opt_redesign_unknown",
        label="OPT portal redesign",
        kind="opt",
        fixture="redesign_unknown.html",
        target_name="Demo OPT Case",
        expected_alert="uncertain",
        description="Readable redesigned page with no known status marker, which should fail loud.",
    ),
    Scenario(
        id="opt_session_expired",
        label="OPT session expired",
        kind="opt",
        fixture="session_expired.html",
        target_name="Demo OPT Case",
        expected_alert="uncertain",
        description="Login/session boundary blocks verification.",
    ),
    Scenario(
        id="opt_maintenance",
        label="OPT portal maintenance",
        kind="opt",
        fixture="portal_maintenance.html",
        target_name="Demo OPT Case",
        expected_alert="uncertain",
        description="Server-side outage blocks verification.",
    ),
    Scenario(
        id="appointment_baseline",
        label="Appointment none available",
        kind="appointment",
        fixture="appointment_none.html",
        target_name="Demo Appointment Slot",
        expected_alert="baseline",
        description="Readable appointment page with no slot available.",
    ),
    Scenario(
        id="appointment_available",
        label="Appointment available",
        kind="appointment",
        fixture="appointment_available.html",
        target_name="Demo Appointment Slot",
        expected_alert="critical",
        description="Appointment slot appears and requires user action.",
    ),
    Scenario(
        id="appointment_captcha",
        label="Appointment captcha",
        kind="appointment",
        fixture="captcha_block.html",
        target_name="Demo Appointment Slot",
        expected_alert="uncertain",
        description="Bot/captcha wall blocks verification.",
    ),
    Scenario(
        id="lease_baseline",
        label="Lease current",
        kind="lease",
        fixture="lease_current.html",
        target_name="Demo Lease Portal",
        expected_alert="baseline",
        description="Readable resident portal with active lease, current rent account, and known notice date.",
    ),
    Scenario(
        id="lease_notice_required",
        label="Lease notice required",
        kind="lease",
        fixture="lease_notice_required.html",
        target_name="Demo Lease Portal",
        expected_alert="critical",
        description="Lease portal changes to require written notice before an earlier deadline.",
    ),
    Scenario(
        id="lease_rent_due",
        label="Rent payment due",
        kind="lease",
        fixture="lease_rent_due.html",
        target_name="Demo Lease Portal",
        expected_alert="critical",
        description="Resident portal shows a rent balance due with a near-term deadline.",
    ),
)


def list_scenarios(kind: str | None = None) -> list[dict[str, Any]]:
    if kind is None:
        return [scenario.to_dict() for scenario in SCENARIOS]
    return [scenario.to_dict() for scenario in SCENARIOS if scenario.kind == kind]


def get_scenario(scenario_id: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.id == scenario_id:
            return scenario
    raise ValueError(f"Unknown scenario: {scenario_id}")


def apply_scenario(paths: Paths, scenario_id: str, *, target_name: str | None = None) -> dict[str, Any]:
    scenario = get_scenario(scenario_id)
    ensure_dirs(paths)
    seed_demo_fixtures(paths)
    target_id = db.upsert_target(
        paths,
        name=target_name or scenario.target_name,
        url=file_url(paths.demo / scenario.fixture),
        kind=scenario.kind,
        high_stakes=True,
        created_at=utc_now(),
    )
    target = db.get_target(paths, target_id=target_id)
    if target is None:
        raise RuntimeError(f"Scenario target was not written: {scenario_id}")
    return target
