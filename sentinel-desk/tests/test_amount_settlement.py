"""Money that already moved is evidence, not a to-do.

"Payment of $3,122.22 has been sent" and "Payment of $3,122.22 is due" differ by
a few words and mean opposite things. Ranking on the word "payment" alone put
completed bank transfers at the very top of a real review queue, above actual
bills -- the highest-priority band filled with items nobody can act on.

These tests pin the distinction at all three layers it has to hold: the
classifier, the extracted fact, and the priority score.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sentineldesk import db
from sentineldesk.config import get_paths
from sentineldesk.email.extract import extract_email_facts
from sentineldesk.email.extract_patterns import (
    SETTLEMENT_INFORMATIONAL,
    SETTLEMENT_OBLIGATION,
    SETTLEMENT_SETTLED,
    classify_amount_settlement,
)
from sentineldesk.email.models import EmailMessage
from sentineldesk.tasks import list_tasks

from tests.dates import iso, timestamp


def _message(message_id: str, subject: str, body: str) -> EmailMessage:
    return EmailMessage(
        message_id=message_id,
        thread_id=f"t-{message_id}",
        sender="alerts@bank.example",
        subject=subject,
        received_at=timestamp(-1),
        body_text=body,
    )


class ClassifierTests(unittest.TestCase):
    SETTLED = [
        "Zelle payment of $3,122.22 to a recipient has been sent",
        "Thank you for your payment of $45.00",
        "Your card was charged $12.99 on Tuesday",
        "We received your payment of $310.00",
        "Refund of $80.00 has been credited to your account",
    ]
    OBLIGATIONS = [
        "Statement balance $1,243.87. Minimum payment due: $35.00",
        "Rent of $1,850.00 is due by 09/01/2026",
        "You will be charged $20.00 on the 3rd",
        "Amount due: $99.00",
        "Please pay $250.00 to avoid a late fee",
    ]
    INFORMATIONAL = [
        "Earn up to $500,000 | $250,000 | $0 across our tiers",
        "Your credit limit is $11,000.00",
        "Prices start at $9.99",
    ]

    def test_settled_language_is_recognised(self) -> None:
        for text in self.SETTLED:
            with self.subTest(text=text):
                self.assertEqual(classify_amount_settlement(text), SETTLEMENT_SETTLED)

    def test_obligation_language_is_recognised(self) -> None:
        for text in self.OBLIGATIONS:
            with self.subTest(text=text):
                self.assertEqual(classify_amount_settlement(text), SETTLEMENT_OBLIGATION)

    def test_amounts_with_no_cue_stay_informational(self) -> None:
        """Neither owed nor paid is the honest answer, not a guess either way."""
        for text in self.INFORMATIONAL:
            with self.subTest(text=text):
                self.assertEqual(classify_amount_settlement(text), SETTLEMENT_INFORMATIONAL)

    def test_an_obligation_beside_a_receipt_still_counts_as_owed(self) -> None:
        # One email can settle one amount and bill the next.
        text = "We received your payment. Your next payment of $200.00 is due Sept 1."
        self.assertEqual(classify_amount_settlement(text), SETTLEMENT_OBLIGATION)


class ExtractedFactTests(unittest.TestCase):
    def test_amount_facts_carry_their_settlement(self) -> None:
        facts = extract_email_facts(
            _message("m1", "Payment sent", "Your payment of $3,122.22 has been sent.")
        )
        amounts = [f for f in facts if f.kind == "amount"]
        self.assertTrue(amounts)
        self.assertEqual(amounts[0].metadata.get("settlement"), SETTLEMENT_SETTLED)

    def test_a_bill_is_marked_as_an_obligation(self) -> None:
        facts = extract_email_facts(
            _message("m2", "Statement ready", "Minimum payment due: $35.00 by 09/02/2026.")
        )
        amounts = [f for f in facts if f.kind == "amount"]
        self.assertTrue(amounts)
        self.assertIn(SETTLEMENT_OBLIGATION, {f.metadata.get("settlement") for f in amounts})


class PriorityTests(unittest.TestCase):
    """The regression that started this: a receipt outranking a bill."""

    def _tasks(self) -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(Path(tmp))
            db.init_db(paths)
            for mid, subject, body in [
                ("m-sent", "Payment sent", "Zelle payment of $3,122.22 to a friend has been sent."),
                ("m-due", "Rent reminder", "Your rent of $1,850.00 is due by 09/01/2026."),
                ("m-promo", "Trade with us", "Earn up to $500,000 | $250,000 | $0 across our tiers."),
            ]:
                message = _message(mid, subject, body)
                db.upsert_email_message(
                    paths, message=message,
                    facts=extract_email_facts(message),
                    ingested_at=timestamp(-1),
                )
            return list_tasks(paths, sort="priority", limit=50)

    def test_a_bill_outranks_a_completed_transfer(self) -> None:
        tasks = {t["primary_source"].split(":")[-1]: t for t in self._tasks() if t["kind"] == "amount"}
        due, sent = tasks["m-due"], tasks["m-sent"]
        self.assertGreater(
            due["priority_score"], sent["priority_score"],
            "a $1,850 bill must outrank a $3,122 transfer that already happened",
        )

    def _amount_task(self, message_id: str) -> dict:
        # A rent email yields both a deadline task and an amount task; only the
        # amount one carries a settlement.
        return next(
            t for t in self._tasks()
            if t["kind"] == "amount" and t["primary_source"].endswith(message_id)
        )

    def test_a_completed_transfer_never_reaches_the_high_band(self) -> None:
        sent = self._amount_task("m-sent")
        self.assertEqual(sent["settlement"], SETTLEMENT_SETTLED)
        self.assertNotEqual(sent["priority_band"], "high")
        self.assertIn("settled_amount", sent["priority_reasons"])
        self.assertNotIn("payment_context", sent["priority_reasons"])

    def test_a_large_marketing_number_never_reaches_the_high_band(self) -> None:
        promo = self._amount_task("m-promo")
        self.assertEqual(promo["settlement"], SETTLEMENT_INFORMATIONAL)
        self.assertNotEqual(promo["priority_band"], "high", "nobody owes a tier table")

    def test_a_real_bill_still_reaches_the_high_band(self) -> None:
        """The fix must not cost recall on the case the queue exists for."""
        due = self._amount_task("m-due")
        self.assertEqual(due["settlement"], SETTLEMENT_OBLIGATION)
        self.assertIn("payment_context", due["priority_reasons"])

    def test_settled_money_stays_in_the_queue_as_evidence(self) -> None:
        """Demoted, not deleted -- "how much did I pay?" is still answerable."""
        sources = {t["primary_source"] for t in self._tasks()}
        self.assertTrue(any(s.endswith("m-sent") for s in sources))


if __name__ == "__main__":
    unittest.main()
