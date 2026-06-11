from __future__ import annotations

import tempfile
import unittest

from sentineldesk import db
from sentineldesk.config import get_paths
from sentineldesk.monitor import run_target
from sentineldesk.scenarios import apply_scenario, get_scenario, list_scenarios


class ScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = get_paths(self.tmp.name)
        db.init_db(self.paths)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_lists_opt_scenarios(self) -> None:
        scenarios = list_scenarios("opt")
        self.assertGreaterEqual(len(scenarios), 5)
        self.assertTrue(all(item["kind"] == "opt" for item in scenarios))

    def test_lists_lease_scenarios(self) -> None:
        scenarios = list_scenarios("lease")
        self.assertGreaterEqual(len(scenarios), 3)
        self.assertTrue(all(item["kind"] == "lease" for item in scenarios))
        self.assertTrue(any(item["id"] == "lease_notice_required" for item in scenarios))

    def test_unknown_scenario_raises(self) -> None:
        with self.assertRaises(ValueError):
            get_scenario("missing")

    def test_apply_scenario_creates_demo_target(self) -> None:
        target = apply_scenario(self.paths, "opt_baseline")
        self.assertEqual(target["name"], "Demo OPT Case")
        self.assertEqual(target["kind"], "opt")
        self.assertTrue(target["url"].startswith("file://"))

    def test_apply_scenario_can_override_target_name(self) -> None:
        target = apply_scenario(self.paths, "appointment_available", target_name="Custom Appointment")
        self.assertEqual(target["name"], "Custom Appointment")
        self.assertEqual(target["kind"], "appointment")

    def test_scenario_transition_produces_expected_alert(self) -> None:
        target = apply_scenario(self.paths, "opt_baseline")
        run_target(self.paths, target)
        target = apply_scenario(self.paths, "opt_action_required")
        run = run_target(self.paths, target)
        self.assertEqual(run["alert"]["level"], "critical")

    def test_lease_notice_transition_produces_critical_alert(self) -> None:
        target = apply_scenario(self.paths, "lease_baseline")
        run_target(self.paths, target)
        target = apply_scenario(self.paths, "lease_notice_required")
        run = run_target(self.paths, target)
        self.assertEqual(run["alert"]["level"], "critical")
        self.assertEqual(run["status"]["value"], "action_required")

    def test_lease_rent_due_transition_produces_critical_alert(self) -> None:
        target = apply_scenario(self.paths, "lease_baseline")
        run_target(self.paths, target)
        target = apply_scenario(self.paths, "lease_rent_due")
        run = run_target(self.paths, target)
        self.assertEqual(run["alert"]["level"], "critical")
        self.assertTrue(run["diff"]["deadline_changed"])


if __name__ == "__main__":
    unittest.main()
