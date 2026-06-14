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


def _cal_item(event_id: str, title: str, date_key: str, *, approval_state: str = "approved", source_id: str = "email:1") -> dict:
    """A calendar item shaped like build_calendar_items output, enough for the overview."""
    return {
        "event_id": event_id,
        "title": title,
        "date_text": date_key,
        "date_key": date_key,
        "approval_state": approval_state,
        "source_ids": [source_id],
    }


class TaskOverviewRoutingTests(unittest.TestCase):
    def test_plate_questions_route_to_overview(self) -> None:
        for question in ["最近有什么要处理", "我有什么待办", "what's on my plate", "give me an overview"]:
            self.assertEqual(classify_intent(question), Intent.TASK_OVERVIEW, question)

    def test_specific_questions_still_win(self) -> None:
        # a deadline/amount keyword must keep its specific intent, not fall to overview
        self.assertEqual(classify_intent("最近有什么截止"), Intent.LATEST_DEADLINE)
        self.assertEqual(classify_intent("最近有什么账单"), Intent.LATEST_AMOUNT)


class TaskOverviewAnswerTests(unittest.TestCase):
    def test_overview_lists_accepted_deadlines(self) -> None:
        # Only what the user accepted into the calendar counts as a fact; every
        # accepted upcoming deadline is listed as a card (sorted nearest-first), a
        # past one is excluded, and grounding stays scoped to the nearest.
        items = [
            _cal_item("e1", "Rent due", "2026-07-01"),
            _cal_item("e2", "Renewal", "2026-08-15"),
            _cal_item("e3", "Old notice", "2026-05-01"),  # past → excluded
        ]
        answer = answer_question("最近有什么要处理", calendar=items)
        self.assertEqual(answer.intent, Intent.TASK_OVERVIEW)
        self.assertFalse(answer.uncertain)
        cards = answer.metadata.get("cards")
        self.assertEqual([c["date"] for c in cards], ["2026-07-01", "2026-08-15"])
        self.assertTrue(cards[0]["title"] and cards[0]["source_id"])
        self.assertEqual(len(answer.citations), 1)  # grounding scoped to the nearest

    def test_overview_lists_all_accepted_not_just_the_nearest(self) -> None:
        items = [_cal_item("e1", "Rent due", "2026-07-01"), _cal_item("e2", "Renewal", "2026-08-15")]
        answer = answer_question("全部列出来", calendar=items, previous_intent="task_overview")
        self.assertEqual(answer.intent, Intent.TASK_OVERVIEW)
        cards = answer.metadata.get("cards")
        self.assertEqual({c["date"] for c in cards}, {"2026-07-01", "2026-08-15"})

    def test_cold_start_points_to_the_review_queue_not_a_blank(self) -> None:
        # Nothing accepted yet, but candidates pending: don't go blank, don't show
        # the candidates as facts in chat — point at the review card.
        items = [
            _cal_item("e1", "Competition Launch", "2026-08-25", approval_state="draft"),
            _cal_item("e2", "Promo", "2026-07-29", approval_state="draft"),
        ]
        answer = answer_question("最近有什么要处理", calendar=items)
        self.assertEqual(answer.intent, Intent.TASK_OVERVIEW)
        self.assertEqual(answer.metadata.get("cards"), [])        # candidates are NOT facts here
        self.assertEqual(answer.metadata.get("pending_count"), 2)
        self.assertIn("复核", answer.answer)                       # nudge to the review queue

    def test_overview_with_nothing_accepted_or_pending(self) -> None:
        answer = answer_question("what's on my plate", calendar=[])
        self.assertEqual(answer.intent, Intent.TASK_OVERVIEW)
        self.assertEqual(answer.metadata.get("cards"), [])
        self.assertIn("还没有截止", answer.answer)


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
        # "全部列出来" is a list-all continuation (and an overview on its own)
        self.assertEqual(classify_intent("全部列出来", previous_intent="task_overview"), Intent.TASK_OVERVIEW)
        self.assertEqual(classify_intent("全部列出来"), Intent.TASK_OVERVIEW)
        # but a specific question still wins over the list-all default
        self.assertEqual(classify_intent("最近有什么截止"), Intent.LATEST_DEADLINE)

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
