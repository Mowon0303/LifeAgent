from __future__ import annotations

import unittest

from sentineldesk.agent.graph import answer_question
from sentineldesk.agent.router import classify_intent
from sentineldesk.agent.schemas import Intent
from sentineldesk.email.models import EmailMessage


def _message(message_id: str, subject: str, body: str, received_at: str = "2026-06-13T00:00:00Z") -> EmailMessage:
    return EmailMessage(
        message_id=message_id, thread_id=f"t-{message_id}", sender="ops@example.com",
        subject=subject, received_at=received_at, body_text=body,
    )


class TaskOverviewRoutingTests(unittest.TestCase):
    def test_plate_questions_route_to_overview(self) -> None:
        for question in ["最近有什么要处理", "我有什么待办", "what's on my plate", "give me an overview"]:
            self.assertEqual(classify_intent(question), Intent.TASK_OVERVIEW, question)

    def test_specific_questions_still_win(self) -> None:
        # a deadline/amount keyword must keep its specific intent, not fall to overview
        self.assertEqual(classify_intent("最近有什么截止"), Intent.LATEST_DEADLINE)
        self.assertEqual(classify_intent("最近有什么账单"), Intent.LATEST_AMOUNT)


class TaskOverviewAnswerTests(unittest.TestCase):
    def test_overview_lists_upcoming_deadlines(self) -> None:
        messages = [
            _message("m1", "Rent due", "Please pay your rent by July 1, 2026."),
            _message("m2", "Renewal", "Submit your renewal by August 15, 2026."),
            _message("m3", "Old notice", "This was due May 1, 2026."),  # past → excluded
        ]
        answer = answer_question("最近有什么要处理", messages=messages)
        self.assertEqual(answer.intent, Intent.TASK_OVERVIEW)
        self.assertFalse(answer.uncertain)
        self.assertIn("2", answer.answer)  # short headline still reports the full count
        # only the nearest upcoming deadline is surfaced as evidence (one card),
        # not a wall of every upcoming date; the past deadline is excluded
        cards = answer.metadata.get("cards")
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["date"], "2026-07-01")  # soonest, not the later 08-15
        self.assertTrue(cards[0]["title"] and cards[0]["source_id"])

    def test_overview_handles_no_evidence(self) -> None:
        answer = answer_question("what's on my plate", messages=[])
        self.assertEqual(answer.intent, Intent.TASK_OVERVIEW)
        self.assertIn("don't see any upcoming", answer.answer)


class FollowupContextTests(unittest.TestCase):
    def test_followup_after_deadline_becomes_overview(self) -> None:
        # "其他的呢" alone is a GENERAL blurb...
        self.assertEqual(classify_intent("其他的呢"), Intent.GENERAL)
        # ...but after a deadline question it continues into the overview.
        self.assertEqual(
            classify_intent("其他的呢", previous_intent="latest_deadline"),
            Intent.TASK_OVERVIEW,
        )
        self.assertEqual(
            classify_intent("还有呢", previous_intent="latest_amount"),
            Intent.TASK_OVERVIEW,
        )

    def test_followup_does_not_hijack_a_real_question(self) -> None:
        # a substantive question keeps its own intent even with a follow-up word
        self.assertEqual(
            classify_intent("这个月要交多少钱", previous_intent="latest_deadline"),
            Intent.LATEST_AMOUNT,
        )

    def test_answer_question_uses_previous_intent(self) -> None:
        messages = [
            _message("m1", "Rent due", "Please pay your rent by July 1, 2026."),
        ]
        answer = answer_question("其他的呢", messages=messages, previous_intent="latest_deadline")
        self.assertEqual(answer.intent, Intent.TASK_OVERVIEW)


if __name__ == "__main__":
    unittest.main()
