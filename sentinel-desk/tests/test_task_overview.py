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
        self.assertIn("2", answer.answer)  # short headline reports the count
        # the per-deadline detail lives in the structured cards (subject, date,
        # source), and the past deadline is excluded
        cards = answer.metadata.get("cards")
        self.assertTrue(cards)
        self.assertEqual({c["date"] for c in cards}, {"2026-07-01", "2026-08-15"})
        self.assertNotIn("2026-05-01", {c["date"] for c in cards})
        self.assertTrue(all(c["title"] and c["source_id"] for c in cards))

    def test_overview_handles_no_evidence(self) -> None:
        answer = answer_question("what's on my plate", messages=[])
        self.assertEqual(answer.intent, Intent.TASK_OVERVIEW)
        self.assertIn("don't see any upcoming", answer.answer)


if __name__ == "__main__":
    unittest.main()
