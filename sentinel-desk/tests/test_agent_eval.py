from __future__ import annotations

import unittest
from pathlib import Path

from sentineldesk.agent.llm import ModelCallResult
from sentineldesk.agent.schemas import Intent
from sentineldesk.evals.agent_eval import _load_jsonl, evaluate_routing, evaluate_slots

ROOT = Path(__file__).resolve().parent.parent
ROUTING_GOLDEN = ROOT / "evals" / "golden" / "agent" / "agent_routing.jsonl"
SLOTS_GOLDEN = ROOT / "evals" / "golden" / "agent" / "calendar_slots.jsonl"


class FakeChat:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    def chat(self, *, system: str, user: str) -> ModelCallResult:
        return ModelCallResult(text=self.reply, prompt_tokens=1, completion_tokens=1, duration_ms=1)


class RoutingGoldenTests(unittest.TestCase):
    def test_golden_is_well_formed(self) -> None:
        cases = _load_jsonl(ROUTING_GOLDEN)
        self.assertGreaterEqual(len(cases), 20)
        valid = {intent.value for intent in Intent}
        for case in cases:
            self.assertIn(case["expected_intent"], valid, case.get("case_id"))

    def test_keyword_clear_cases_route_deterministically_at_100(self) -> None:
        # The CI regression gate: the deterministic keyword layer (no model) must nail
        # every keyword-clear case. The model-dependent cases are measured in a live run.
        report = evaluate_routing(ROUTING_GOLDEN, client=None)
        self.assertEqual(report.keyword_clear_accuracy, 1.0, report.failures)


class SlotEvalHarnessTests(unittest.TestCase):
    def test_scoring_marks_a_correct_extraction_and_runs(self) -> None:
        # A model that returns the right slots for the absolute dentist case scores it
        # correct — guards the harness/scoring independent of any real model.
        client = FakeChat('{"title":"牙医预约","date":"2026-06-20","start_time":"15:00","end_time":""}')
        report = evaluate_slots(SLOTS_GOLDEN, client=client)
        self.assertNotIn("slot-abs-time", {f["case_id"] for f in report.failures})
        self.assertIsNotNone(report.date_accuracy)


if __name__ == "__main__":
    unittest.main()
