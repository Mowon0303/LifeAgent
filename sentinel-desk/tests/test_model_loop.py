from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sentineldesk import db
from sentineldesk.agent.llm import ModelCallResult, fact_anchors, refine_answer
from sentineldesk.agent.model import ModelProvider
from sentineldesk.agent.schemas import AgentAnswer, Citation, Intent
from sentineldesk.agent.workflow import answer_with_workflow
from sentineldesk.config import ensure_dirs, get_paths
from sentineldesk.email.models import EmailMessage

OLLAMA_PROVIDER = ModelProvider(provider="ollama", model="qwen2.5:7b", base_url="http://127.0.0.1:11434")
LOCAL_PROVIDER = ModelProvider(provider="local", model="rule-router")


class FakeChatClient:
    def __init__(self, reply: str, *, error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[dict[str, str]] = []

    def chat(self, *, system: str, user: str) -> ModelCallResult:
        self.calls.append({"system": system, "user": user})
        if self.error is not None:
            raise self.error
        return ModelCallResult(text=self.reply, prompt_tokens=120, completion_tokens=40, duration_ms=850)


def verified_answer() -> AgentAnswer:
    return AgentAnswer(
        intent=Intent.LATEST_DEADLINE,
        answer="Verified deadline: 07/01/2026",
        confidence="high",
        citations=(
            Citation(
                source_id="email:ui-sample-rent-001",
                source_type="email",
                evidence="Your July rent payment of $1,850.00 is due by 07/01/2026.",
                captured_at="2026-06-25T09:00:00+00:00",
            ),
        ),
        tool_calls=("search_latest_email",),
    )


class FactAnchorTests(unittest.TestCase):
    def test_anchors_capture_dates_and_amounts_once(self) -> None:
        anchors = fact_anchors("Pay $1,850.00 by 07/01/2026. Again: $1,850.00 on July 1, 2026.")
        self.assertEqual(anchors, ["07/01/2026", "July 1, 2026", "$1,850.00"])


class RefineAnswerTests(unittest.TestCase):
    def test_successful_rewrite_keeps_facts_and_records_tokens(self) -> None:
        client = FakeChatClient("你的下一个截止日期是 07/01/2026，按时处理就好。")
        answer, record = refine_answer(
            verified_answer(), question="我的最近截止日期是什么？", provider=OLLAMA_PROVIDER, client=client
        )
        self.assertEqual(record.status, "ok")
        self.assertEqual(record.prompt_tokens, 120)
        self.assertEqual(record.completion_tokens, 40)
        self.assertIn("07/01/2026", answer.answer)
        self.assertNotEqual(answer.answer, "Verified deadline: 07/01/2026")
        self.assertEqual(answer.metadata["deterministic_answer"], "Verified deadline: 07/01/2026")
        self.assertEqual(answer.confidence, "high")
        self.assertEqual(len(client.calls), 1)
        self.assertIn("<question>", client.calls[0]["user"])

    def test_rewrite_dropping_anchor_falls_back(self) -> None:
        client = FakeChatClient("你的下一个截止日期快到了，请尽快处理。")
        answer, record = refine_answer(
            verified_answer(), question="最近截止？", provider=OLLAMA_PROVIDER, client=client
        )
        self.assertEqual(record.status, "fallback_anchor_check")
        self.assertIn("07/01/2026", record.detail)
        self.assertEqual(answer.answer, "Verified deadline: 07/01/2026")

    def test_rewrite_inventing_new_facts_falls_back(self) -> None:
        client = FakeChatClient("截止日期是 07/01/2026，记得同时支付 $9,999 手续费。")
        answer, record = refine_answer(
            verified_answer(), question="最近截止？", provider=OLLAMA_PROVIDER, client=client
        )
        self.assertEqual(record.status, "fallback_new_facts")
        self.assertIn("$9,999", record.detail)
        self.assertEqual(answer.answer, "Verified deadline: 07/01/2026")

    def test_model_error_falls_back_and_is_recorded(self) -> None:
        client = FakeChatClient("", error=OSError("connection refused"))
        answer, record = refine_answer(
            verified_answer(), question="最近截止？", provider=OLLAMA_PROVIDER, client=client
        )
        self.assertEqual(record.status, "fallback_error")
        self.assertEqual(record.detail, "OSError")
        self.assertEqual(answer.answer, "Verified deadline: 07/01/2026")

    def test_uncertain_answers_are_never_sent_to_the_model(self) -> None:
        client = FakeChatClient("should never be used")
        uncertain = AgentAnswer(
            intent=Intent.LATEST_DEADLINE,
            answer="I cannot verify the latest fact from available email evidence.",
            confidence="uncertain",
            uncertain=True,
        )
        answer, record = refine_answer(
            uncertain, question="最近截止？", provider=OLLAMA_PROVIDER, client=client
        )
        self.assertEqual(record.status, "skipped_uncertain")
        self.assertEqual(answer.answer, uncertain.answer)
        self.assertEqual(client.calls, [])

    def test_free_mode_keeps_a_rewrite_the_guard_would_reject(self) -> None:
        # The rewrite drops the explicit date — guarded refine falls back, but
        # free_refine keeps the natural synthesis and uses the report prompt.
        free = ModelProvider(provider="ollama", model="qwen2.5:7b", free_refine=True)
        client = FakeChatClient("房租快到期了，记得尽快缴纳 1850 元。")
        answer, record = refine_answer(
            verified_answer(), question="最近截止？", provider=free, client=client
        )
        self.assertEqual(record.status, "ok_free")
        self.assertEqual(answer.answer, "房租快到期了，记得尽快缴纳 1850 元。")
        self.assertIn("report", client.calls[0]["system"].lower())

    def test_free_mode_also_rewrites_uncertain_answers(self) -> None:
        free = ModelProvider(provider="ollama", model="qwen2.5:7b", free_refine=True)
        client = FakeChatClient("有几个互相冲突的截止日期，建议你逐一核对。")
        uncertain = AgentAnswer(
            intent=Intent.LATEST_DEADLINE,
            answer="Conflicting deadline evidence found: 07/01/2026, 07/02/2026.",
            confidence="uncertain",
            uncertain=True,
        )
        answer, record = refine_answer(uncertain, question="最近截止？", provider=free, client=client)
        self.assertEqual(record.status, "ok_free")
        self.assertEqual(answer.answer, "有几个互相冲突的截止日期，建议你逐一核对。")
        self.assertTrue(answer.uncertain)  # still flagged uncertain, just phrased naturally

    def test_free_mode_blocks_an_invented_date(self) -> None:
        # The core "串台" regression: free mode may rephrase, but a date that is in
        # neither the base answer nor its evidence (e.g. borrowed from another
        # email) must be rejected back to the grounded answer.
        free = ModelProvider(provider="ollama", model="qwen2.5:7b", free_refine=True)
        client = FakeChatClient("提醒你：这个优惠的截止其实是 08/25/2026，请尽快处理。")
        answer, record = refine_answer(
            verified_answer(), question="最近截止？", provider=free, client=client
        )
        self.assertEqual(record.status, "fallback_new_facts")
        self.assertIn("08/25/2026", record.detail)
        self.assertEqual(answer.answer, "Verified deadline: 07/01/2026")

    def test_free_mode_allows_bare_counts_and_grounded_dates(self) -> None:
        # A natural rewrite that keeps the grounded date and mentions a plain count
        # ("3 封") must NOT be rejected — counts/years aren't currency anchors.
        free = ModelProvider(provider="ollama", model="qwen2.5:7b", free_refine=True)
        client = FakeChatClient("你的截止 07/01/2026 快到了，我一共找到 3 封相关邮件，记得缴 $1,850.00。")
        answer, record = refine_answer(
            verified_answer(), question="最近截止？", provider=free, client=client
        )
        self.assertEqual(record.status, "ok_free")
        self.assertIn("3 封", answer.answer)

    def test_confirmation_boundaries_are_never_sent_to_the_model(self) -> None:
        client = FakeChatClient("should never be used")
        boundary = AgentAnswer(
            intent=Intent.CALENDAR_ACTION,
            answer="I can draft a calendar event, but external calendar sync requires explicit confirmation.",
            confidence="medium",
            requires_confirmation=True,
        )
        answer, record = refine_answer(
            boundary, question="帮我加日历", provider=OLLAMA_PROVIDER, client=client
        )
        self.assertEqual(record.status, "skipped_confirmation_boundary")
        self.assertEqual(client.calls, [])

    def test_local_provider_skips_model_path_entirely(self) -> None:
        answer, record = refine_answer(
            verified_answer(), question="最近截止？", provider=LOCAL_PROVIDER, client=None
        )
        self.assertIsNone(record)
        self.assertEqual(answer.answer, "Verified deadline: 07/01/2026")


class WorkflowModelLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = get_paths(self.tmp.name)
        ensure_dirs(self.paths)
        db.init_db(self.paths)
        self.messages = [
            EmailMessage(
                message_id="loop-rent-001",
                thread_id="loop-thread",
                sender="billing@parkview-residences.example",
                subject="Rent payment reminder",
                received_at="2026-06-25T09:00:00+00:00",
                body_text="Your July rent payment of $1,850.00 is due by 07/01/2026. Please pay online.",
            )
        ]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_workflow_refines_verified_answer_and_persists_model_call(self) -> None:
        client = FakeChatClient("最近的截止日期是 07/01/2026：七月房租。")
        answer = answer_with_workflow(
            "What is my latest deadline?",
            provider=OLLAMA_PROVIDER,
            messages=self.messages,
            paths=self.paths,
            chat_client=client,
        )
        self.assertIn("07/01/2026", answer.answer)
        self.assertEqual(answer.metadata["model_call"]["status"], "ok")
        self.assertEqual(answer.metadata["model_call"]["completion_tokens"], 40)
        stages = [item["stage"] for item in answer.metadata["workflow_trace"]]
        self.assertIn("refine", stages)
        calls = db.list_model_calls(self.paths)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["status"], "ok")
        self.assertEqual(calls[0]["intent"], "latest_deadline")
        summary = db.model_calls_summary(self.paths)
        self.assertEqual(summary["call_count"], 1)
        self.assertEqual(summary["total_tokens"], 160)
        self.assertEqual(summary["refine_success_rate"], 1.0)

    def test_workflow_uncertain_answer_stays_deterministic_and_is_attributed(self) -> None:
        client = FakeChatClient("should never be used")
        answer = answer_with_workflow(
            "What is my latest deadline?",
            provider=OLLAMA_PROVIDER,
            messages=[],
            paths=self.paths,
            chat_client=client,
        )
        self.assertTrue(answer.uncertain)
        self.assertEqual(answer.metadata["model_call"]["status"], "skipped_uncertain")
        self.assertEqual(client.calls, [])
        calls = db.list_model_calls(self.paths)
        self.assertEqual(calls[0]["status"], "skipped_uncertain")
        self.assertEqual(calls[0]["prompt_tokens"], 0)

    def test_workflow_local_provider_records_nothing(self) -> None:
        answer = answer_with_workflow(
            "What is my latest deadline?",
            provider=LOCAL_PROVIDER,
            messages=self.messages,
            paths=self.paths,
        )
        self.assertNotIn("model_call", answer.metadata)
        self.assertEqual(db.list_model_calls(self.paths), [])


if __name__ == "__main__":
    unittest.main()
