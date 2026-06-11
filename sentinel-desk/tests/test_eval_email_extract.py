from __future__ import annotations

import unittest

from sentineldesk.config import project_root
from sentineldesk.evals.email_extract import (
    HIGH_CONFIDENCE_THRESHOLD,
    evaluate_golden_path,
    load_golden_cases,
)

GOLDEN_DIR = project_root() / "evals" / "golden"

EXPECTED_CATEGORIES = {
    "lease_rent",
    "billing_utility",
    "bank_card",
    "immigration_school",
    "subscription_services",
    "insurance_medical",
    "tax_government",
    "edge_cases",
    "negatives",
    "adversarial",
}

# Regression floors sit just below the measured baseline (2026-06-11 after
# relative-deadline, date-form, non-dollar/spelled-out amount,
# high-confidence amount false-positive filters, and action-lexicon support:
# raw deadline P=0.763/R=0.975, raw amount P=0.864/R=1.000,
# raw action P=0.885/R=1.000,
# high-conf deadline P=0.852/R=0.566, high-conf amount P=0.977/R=0.553).
# A failure here means extraction quality regressed or the golden set drifted;
# improvements should raise these floors deliberately.
RAW_FLOORS = {
    "deadline": {"precision": 0.75, "recall": 0.96},
    "amount": {"precision": 0.85, "recall": 0.99},
    "action": {"precision": 0.87, "recall": 0.98},
}
HIGH_CONFIDENCE_FLOORS = {
    "deadline": {"precision": 0.84, "recall": 0.55},
    "amount": {"precision": 0.96, "recall": 0.54},
}


class GoldenSetIntegrityTests(unittest.TestCase):
    def test_golden_set_loads_with_expected_shape(self) -> None:
        cases = load_golden_cases(GOLDEN_DIR)
        self.assertGreaterEqual(len(cases), 140)
        categories: dict[str, int] = {}
        for case in cases:
            categories[case.category] = categories.get(case.category, 0) + 1
            self.assertTrue(case.case_id)
            self.assertTrue(case.message.searchable_text.strip())
        self.assertEqual(set(categories), EXPECTED_CATEGORIES)
        for category, count in categories.items():
            self.assertGreaterEqual(count, 8, f"category {category} is too small")

    def test_case_ids_are_unique(self) -> None:
        cases = load_golden_cases(GOLDEN_DIR)
        case_ids = [case.case_id for case in cases]
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_senders_stay_on_example_domains(self) -> None:
        for case in load_golden_cases(GOLDEN_DIR):
            self.assertTrue(
                case.message.sender.endswith(".example"),
                f"{case.case_id}: golden senders must use .example domains",
            )


class EmailExtractEvalGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = evaluate_golden_path(GOLDEN_DIR)

    def test_raw_layer_metric_floors(self) -> None:
        for kind, floors in RAW_FLOORS.items():
            tally = self.report.overall["raw"][kind]
            self.assertIsNotNone(tally.precision, f"raw.{kind} has no predictions")
            self.assertGreaterEqual(
                tally.precision, floors["precision"], f"raw.{kind} precision regressed"
            )
            self.assertGreaterEqual(tally.recall, floors["recall"], f"raw.{kind} recall regressed")

    def test_high_confidence_metric_floors(self) -> None:
        for kind, floors in HIGH_CONFIDENCE_FLOORS.items():
            tally = self.report.overall["high_confidence"][kind]
            self.assertIsNotNone(tally.precision, f"high_confidence.{kind} has no predictions")
            self.assertGreaterEqual(
                tally.precision, floors["precision"], f"high_confidence.{kind} precision regressed"
            )
            self.assertGreaterEqual(
                tally.recall, floors["recall"], f"high_confidence.{kind} recall regressed"
            )

    def test_risk_word_heuristic_improves_precision(self) -> None:
        for kind in ("deadline", "amount"):
            high = self.report.confidence_buckets["high"][kind]
            low = self.report.confidence_buckets["low"][kind]
            self.assertIsNotNone(high.precision)
            self.assertIsNotNone(low.precision)
            self.assertGreater(
                high.precision,
                low.precision,
                f"{kind}: confidence >= {HIGH_CONFIDENCE_THRESHOLD} bucket should be more precise",
            )

    def test_action_confidence_is_flat_by_construction(self) -> None:
        tally = self.report.overall["high_confidence"]["action"]
        self.assertEqual(
            tally.true_positives + tally.false_positives,
            0,
            "action facts gained confidence tiers; update the eval layers and report notes",
        )

    def test_suppression_injection_does_not_hide_real_facts(self) -> None:
        result = next(item for item in self.report.case_results if item.case_id == "adv-010")
        deadline = result.layers["raw"]["deadline"]
        amount = result.layers["raw"]["amount"]
        self.assertIn("06/27/2026", deadline.true_positives)
        self.assertIn("$233.10", amount.true_positives)
        self.assertFalse(deadline.false_negatives)
        self.assertFalse(amount.false_negatives)

    def test_negative_categories_only_produce_false_positives(self) -> None:
        for result in self.report.case_results:
            if result.category not in {"negatives", "adversarial"}:
                continue
            if result.case_id in {"adv-005", "adv-009", "adv-010"}:
                continue
            for kind_result in result.layers["raw"].values():
                self.assertFalse(
                    kind_result.false_negatives,
                    f"{result.case_id}: pure negative cases should have no expected facts",
                )


if __name__ == "__main__":
    unittest.main()
