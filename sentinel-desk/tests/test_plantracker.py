from __future__ import annotations

import unittest

from sentineldesk.plantracker import format_plan_summary, parse_response_condition, parse_status_table, summarize_plan


MARKDOWN = """
# Tracker

## Response Condition

- Rule: Every plan-status reply must show completed plans and the next plan to complete.
- Next plan to complete: Polish the demo script.

## Status Table

| Area | Status | Evidence | Next Work |
| --- | --- | --- | --- |
| Cleanup | Done | Removed old files | Keep root clean |
| Demo | Partial | Dashboard exists | Browser QA |

## Later
"""


class PlanTrackerTests(unittest.TestCase):
    def test_parse_status_table(self) -> None:
        items = parse_status_table(MARKDOWN)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].area, "Cleanup")
        self.assertEqual(items[1].status, "Partial")

    def test_parse_response_condition(self) -> None:
        condition = parse_response_condition(MARKDOWN)
        self.assertEqual(condition["next plan to complete"], "Polish the demo script.")

    def test_summarize_real_tracker(self) -> None:
        summary = summarize_plan()
        self.assertGreaterEqual(summary["completed_count"], 1)
        self.assertIn("completed_plans", summary)
        self.assertIn("next_plan", summary)

    def test_format_summary_has_required_reply_blocks(self) -> None:
        summary = {
            "completed_plans": [{"area": "Cleanup", "evidence": "Removed old files"}],
            "next_plan": {"area": "Response condition", "work": "Polish the demo script."},
        }
        text = format_plan_summary(summary)
        self.assertIn("已完成的计划", text)
        self.assertIn("下一个该完成的计划", text)


if __name__ == "__main__":
    unittest.main()
