"""What the assistant says has to be true of the mailbox it looked at.

Every case here comes from P3 day 1: the same five questions asked against a
real 40-message inbox. The task queue held up -- evidence was complete on all 23
items -- and every defect was in the answer layer:

* it reported an empty review queue while 19 cards were waiting,
* it answered a deadline question with a portal excuse and four citations, none
  of which contained a deadline,
* it called a wire the user had sent "conflicting evidence" against the one real
  debt, and
* it answered Chinese questions in English.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sentineldesk import db
from sentineldesk.agent.graph import answer_question
from sentineldesk.agent.graph.facts import asked_in_chinese, prefer_obligation_amounts
from sentineldesk.agent.graph.portal import _is_portal_trigger, _portal_trigger_citations
from sentineldesk.agent.router import classify_intent
from sentineldesk.agent.schemas import Intent
from sentineldesk.agent.tools import default_tool_registry
from sentineldesk.config import get_paths
from sentineldesk.email.extract import extract_email_facts
from sentineldesk.email.models import EmailMessage

from tests.dates import timestamp


def _email(message_id: str, subject: str, body: str, *, sender: str = "alerts@bank.example") -> EmailMessage:
    return EmailMessage(
        message_id=message_id,
        thread_id=f"t-{message_id}",
        sender=sender,
        subject=subject,
        received_at=timestamp(-1),
        body_text=body,
    )


class RoutingTests(unittest.TestCase):
    def test_natural_chinese_payment_phrasings_reach_the_amount_intent(self) -> None:
        """"我欠了多少钱" routed; "我最近有哪些要付的钱" fell through to GENERAL."""
        for question in [
            "我最近有哪些要付的钱？",
            "我欠了多少钱？",
            "这个月要交多少钱？",
            "有什么要付款的吗？",
            "该交的房租是多少？",
        ]:
            with self.subTest(question=question):
                self.assertEqual(classify_intent(question), Intent.LATEST_AMOUNT)

    def test_a_substring_does_not_hijack_an_unrelated_question(self) -> None:
        """"owe" hides inside "lowest" -- the reason bare stems stay out."""
        self.assertNotEqual(
            classify_intent("tell me about the Tripalink renewal lowest rate offer"),
            Intent.LATEST_AMOUNT,
        )


class ObligationPreferenceTests(unittest.TestCase):
    def test_a_sent_wire_does_not_conflict_with_a_real_debt(self) -> None:
        owed = extract_email_facts(
            _email("m-debt", "Notice", "You still have an outstanding balance of $31.05 on your policy.")
        )
        wire = extract_email_facts(
            _email("m-wire", "Wire request", "We received your wire transfer request. Amount $11,000.00 Transfer fee $45.00")
        )
        amounts = [f for f in [*owed, *wire] if f.kind == "amount"]
        self.assertGreater(len(amounts), 1, "the fixture must produce competing amounts")
        kept = prefer_obligation_amounts(amounts)
        self.assertTrue(kept)
        self.assertEqual({f.value for f in kept}, {"$31.05"})

    def test_with_no_obligation_every_amount_is_kept(self) -> None:
        """Filtering must not empty the queue when nothing is classified as owed."""
        facts = extract_email_facts(_email("m-info", "Coverage", "Protected up to $500,000 per account."))
        amounts = [f for f in facts if f.kind == "amount"]
        self.assertEqual(prefer_obligation_amounts(amounts), amounts)


class PortalTriggerTests(unittest.TestCase):
    def test_a_sign_in_alert_is_not_a_portal_deadline_trigger(self) -> None:
        """A security alert reports a sign-in that happened; it asks for nothing."""
        alert = _email("m-alert", "New sign-in to your OpenAI account",
                       "We noticed a new sign-in to your account. If this was not you, secure your account.")
        self.assertFalse(_is_portal_trigger(alert))
        self.assertEqual(_portal_trigger_citations([alert]), ())

    def test_a_portal_message_with_a_deadline_still_triggers(self) -> None:
        """Narrowing must not lose the case the portal path exists for."""
        notice = _email("m-portal", "Action needed",
                        "Log in to the portal to see your payment due date before the grace period ends.")
        self.assertTrue(_is_portal_trigger(notice))

    def test_citation_evidence_is_readable_text_not_markup(self) -> None:
        """Drill-down showed `<!DOCTYPE html><html lang="en" ...` instead of the sentence."""
        notice = _email(
            "m-html", "Payment due",
            '<!DOCTYPE html><html lang="en"><body><p>Log in to the portal. '
            'Your payment due date is 09/01/2026.</p></body></html>',
        )
        citations = _portal_trigger_citations([notice])
        self.assertEqual(len(citations), 1)
        evidence = citations[0].evidence
        self.assertNotIn("<!DOCTYPE", evidence)
        self.assertNotIn("<html", evidence)
        self.assertIn("payment due date", evidence.lower())


class OverviewHonestyTests(unittest.TestCase):
    """The sentence that was simply false on a real mailbox."""

    def _answer(self, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(Path(tmp))
            db.init_db(paths)
            return answer_question(
                "我有哪些待办？", messages=[], registry=default_tool_registry(paths),
                calendar=[], **kwargs,
            )

    def test_it_never_claims_an_empty_review_queue_it_did_not_check(self) -> None:
        answer = self._answer()  # review_queue_count omitted == unknown
        self.assertNotIn("没有待复核", answer.answer)
        self.assertIn("日历", answer.answer)

    def test_a_waiting_review_queue_is_reported(self) -> None:
        answer = self._answer(review_queue_count=19)
        self.assertIn("19", answer.answer)
        self.assertEqual(answer.metadata.get("review_queue_count"), 19)

    def test_a_genuinely_empty_queue_may_be_called_empty(self) -> None:
        answer = self._answer(review_queue_count=0)
        self.assertIn("空", answer.answer)


class AnswerLanguageTests(unittest.TestCase):
    def test_a_chinese_question_is_detected(self) -> None:
        self.assertTrue(asked_in_chinese("这个月要交多少钱？"))
        self.assertFalse(asked_in_chinese("how much do I owe?"))

    def test_a_chinese_amount_question_is_answered_in_chinese(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(Path(tmp))
            db.init_db(paths)
            message = _email("m-debt", "Notice", "You still have an outstanding balance of $31.05 on your policy.")
            answer = answer_question(
                "这个月要交多少钱？", messages=[message], registry=default_tool_registry(paths),
            )
        self.assertTrue(asked_in_chinese(answer.answer), answer.answer)
        self.assertIn("$31.05", answer.answer)

    def test_an_english_question_keeps_its_english_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(Path(tmp))
            db.init_db(paths)
            message = _email("m-debt", "Notice", "You still have an outstanding balance of $31.05 on your policy.")
            answer = answer_question(
                "how much do I owe?", messages=[message], registry=default_tool_registry(paths),
            )
        self.assertFalse(asked_in_chinese(answer.answer), answer.answer)
        self.assertIn("$31.05", answer.answer)


if __name__ == "__main__":
    unittest.main()
