from __future__ import annotations

import unittest

from sentineldesk.agent.memory import (
    DEFAULT_HISTORY_BUDGET_TOKENS,
    _est_tokens,
    build_memory,
)


class BuildMemoryTests(unittest.TestCase):
    def test_empty_and_none_history_are_empty(self) -> None:
        for hist in ([], None):
            memory = build_memory(hist)
            self.assertTrue(memory.is_empty())
            self.assertEqual(memory.as_prompt_block(), "")

    def test_short_history_rides_verbatim_with_no_summary(self) -> None:
        hist = [
            {"question": "最近有什么截止", "intent": "task_overview", "answer": "你有 5 个截止"},
            {"question": "比如呢", "intent": "task_overview", "answer": "Tripalink 2026-06-15 $998"},
        ]
        memory = build_memory(hist)
        self.assertEqual(memory.summary, "")
        self.assertEqual(len(memory.recent), 2)
        block = memory.as_prompt_block()
        self.assertIn("最近对话", block)
        self.assertIn("比如呢", block)          # the follow-up survives for the model
        self.assertIn("Tripalink 2026-06-15 $998", block)

    def test_overflow_folds_oldest_into_a_structured_gist(self) -> None:
        hist = [
            {"question": "房租多少钱", "intent": "latest_amount", "answer": "$998 due 2026-06-15"},
            {"question": "下一步怎么办", "intent": "next_step_recommendation", "answer": "建议尽快缴费"},
            {"question": "还有别的吗", "intent": "task_overview", "answer": "另有 3 封相关邮件"},
        ]
        memory = build_memory(hist, budget_tokens=5)  # tiny budget -> only newest stays verbatim
        self.assertTrue(memory.summary)
        self.assertGreaterEqual(len(memory.recent), 1)
        # the gist keeps the topics and the load-bearing entities for later reference
        self.assertIn("latest_amount", memory.summary)
        self.assertIn("$998", memory.summary)
        self.assertIn("2026-06-15", memory.summary)
        # ...and the newest turn is still verbatim, not compacted
        self.assertEqual(memory.recent[-1].question, "还有别的吗")

    def test_gist_captures_chinese_dates_and_amounts(self) -> None:
        hist = [
            {"question": "押金啥时候退", "intent": "latest_deadline", "answer": "6月15日退 1200 美元"},
            {"question": "a", "intent": "x", "answer": "b"},
        ]
        memory = build_memory(hist, budget_tokens=1)
        self.assertIn("6月15日", memory.summary)
        self.assertIn("1200 美元", memory.summary)

    def test_turns_without_a_question_are_skipped(self) -> None:
        hist = [
            {"intent": "x", "answer": "no question here"},
            {"question": "真问题", "intent": "task_overview", "answer": "答"},
        ]
        memory = build_memory(hist)
        self.assertEqual(len(memory.recent), 1)
        self.assertEqual(memory.recent[0].question, "真问题")

    def test_long_answer_is_digested_in_the_block(self) -> None:
        memory = build_memory(
            [{"question": "q", "intent": "task_overview", "answer": "字" * 500}]
        )
        block = memory.as_prompt_block()
        self.assertIn("…", block)               # trimmed, not dumped whole
        self.assertLess(len(block), 500)

    def test_token_estimate_counts_cjk_heavier_than_latin(self) -> None:
        self.assertGreater(_est_tokens("中文中文中文"), _est_tokens("abcdef"))
        self.assertEqual(_est_tokens(""), 0)

    def test_default_budget_is_generous_enough_for_a_dozen_short_turns(self) -> None:
        hist = [
            {"question": "第 %d 个问题" % i, "intent": "task_overview", "answer": "第 %d 个答复" % i}
            for i in range(12)
        ]
        memory = build_memory(hist, budget_tokens=DEFAULT_HISTORY_BUDGET_TOKENS)
        self.assertEqual(memory.summary, "")     # a dozen short turns fit without compaction
        self.assertEqual(len(memory.recent), 12)


if __name__ == "__main__":
    unittest.main()
