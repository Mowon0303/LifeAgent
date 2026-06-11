from __future__ import annotations

import tempfile
import unittest

from sentineldesk.config import ensure_config, get_paths
from sentineldesk.policy import list_policies, load_policy, normalize_kind, policy_for_kind


class PolicyTests(unittest.TestCase):
    def test_kind_aliases_route_to_opt_policy(self) -> None:
        self.assertEqual(normalize_kind("uscis"), "opt")
        self.assertEqual(normalize_kind("ois"), "opt")

    def test_opt_policy_fails_on_unknown_status(self) -> None:
        policy = policy_for_kind("opt", high_stakes=True)
        self.assertTrue(policy.fail_on_unknown_status)
        self.assertEqual(policy.meaningful_change_level, "critical")

    def test_low_stakes_disables_unknown_fail_loud(self) -> None:
        policy = policy_for_kind("opt", high_stakes=False)
        self.assertFalse(policy.fail_on_unknown_status)
        self.assertEqual(policy.meaningful_change_level, "warning")

    def test_appointment_policy_has_vertical_label(self) -> None:
        policy = policy_for_kind("appointment", high_stakes=True)
        self.assertIn("Appointment", policy.label)

    def test_unknown_kind_uses_generic_policy(self) -> None:
        policy = policy_for_kind("unknown-kind", high_stakes=True)
        self.assertEqual(policy.kind, "generic")

    def test_config_override_changes_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            paths.home.mkdir(parents=True, exist_ok=True)
            paths.config.write_text(
                """
[vertical.opt]
label = "Custom OPT"
fail_on_unknown_status = false
meaningful_change_level = "warning"
text_change_level = "none"
""",
                encoding="utf-8",
            )
            policy = load_policy(paths, "opt", high_stakes=True)
        self.assertEqual(policy.label, "Custom OPT")
        self.assertFalse(policy.fail_on_unknown_status)
        self.assertEqual(policy.meaningful_change_level, "warning")

    def test_default_config_exposes_policies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            paths.home.mkdir(parents=True, exist_ok=True)
            ensure_config(paths)
            policies = list_policies(paths)
        self.assertTrue(any(policy["kind"] == "opt" for policy in policies))


if __name__ == "__main__":
    unittest.main()
