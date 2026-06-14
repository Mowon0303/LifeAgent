from __future__ import annotations

import tempfile
import unittest

from sentineldesk import db
from sentineldesk.config import get_paths
from sentineldesk.email.extract import extract_email_facts
from sentineldesk.email.ingest import stored_email_messages
from sentineldesk.email.models import EmailMessage


def _message(*, labels: tuple[str, ...] = (), list_unsubscribe: str = "", body: str) -> EmailMessage:
    return EmailMessage(
        message_id="m1",
        thread_id="t1",
        sender="Lewd Lad <lewd_lad@creator.patreon.com>",
        subject="Promeia Megatoggle Deluxe (Uncensored Gallery)",
        received_at="2026-06-04T00:00:00Z",
        body_text=body,
        source_type="gmail",
        trust_label="email_provider_api",
        labels=labels,
        list_unsubscribe=list_unsubscribe,
    )


def _deadlines(message: EmailMessage) -> list[str]:
    return [fact.value for fact in extract_email_facts(message) if fact.kind == "deadline"]


def _kinds(message: EmailMessage, kind: str) -> list[str]:
    return [fact.value for fact in extract_email_facts(message) if fact.kind == kind]


class GmailCategoryGateTests(unittest.TestCase):
    def test_gmail_category_and_is_bulk_derive_from_signals(self) -> None:
        promo = _message(labels=("INBOX", "UNREAD", "CATEGORY_PROMOTIONS"), body="x")
        self.assertEqual(promo.gmail_category, "promotions")
        social = _message(labels=("CATEGORY_SOCIAL",), body="x")
        self.assertEqual(social.gmail_category, "social")
        personal = _message(labels=("INBOX", "CATEGORY_PERSONAL"), body="x")
        self.assertEqual(personal.gmail_category, "primary")
        legacy = _message(labels=(), body="x")  # older evidence / non-Gmail
        self.assertEqual(legacy.gmail_category, "")
        self.assertTrue(_message(list_unsubscribe="<https://x/u>", body="x").is_bulk)
        self.assertFalse(_message(body="x").is_bulk)

    def test_promotional_post_date_is_not_a_deadline(self) -> None:
        """The real failure: a Patreon post-publication date in a Promotions
        email became a 0.76 'deadline'. The category gate must drop it."""
        body = "New post is live! Jun 4, 2026 View in app View in app Download Lewd Access"
        promo = _message(labels=("CATEGORY_PROMOTIONS",), body=body)
        self.assertEqual(_deadlines(promo), [])

    def test_same_date_still_extracts_in_a_primary_message(self) -> None:
        """Without the promotional label the extractor behaves as before — the
        gate is the differentiator, not some unrelated filter."""
        body = "New post is live! Jun 4, 2026 View in app View in app Download Lewd Access"
        primary = _message(labels=("INBOX", "CATEGORY_PERSONAL"), body=body)
        self.assertIn("Jun 4, 2026", _deadlines(primary))

    def test_promotional_message_with_real_obligation_survives(self) -> None:
        """A promo that genuinely asks the user to act by a date is kept — the
        gate only drops promos with no user obligation."""
        body = "Final reminder: please respond by July 1, 2026 to keep your account."
        promo = _message(labels=("CATEGORY_PROMOTIONS",), body=body)
        self.assertIn("July 1, 2026", _deadlines(promo))

    def test_distant_footer_obligation_text_does_not_rescue_promo_date(self) -> None:
        body = (
            "New creator post is live! May 6, 2026 View in app Download. "
            + ("member update " * 40)
            + "This notice is required by law and includes unsubscribe terms."
        )
        promo = _message(labels=("CATEGORY_PROMOTIONS",), body=body)
        self.assertEqual(_deadlines(promo), [])

    def test_promotional_offer_purchase_by_date_is_gated(self) -> None:
        body = "Terms and conditions: Vacation package must be purchased by June 26, 2026."
        promo = _message(labels=("CATEGORY_PROMOTIONS",), list_unsubscribe="<https://x/u>", body=body)
        self.assertEqual(_deadlines(promo), [])

    def test_bulk_mail_without_obligation_is_gated(self) -> None:
        body = "Our weekly digest for Jun 4, 2026. Browse the latest stories."
        bulk = _message(list_unsubscribe="<mailto:unsub@list.example>", body=body)
        self.assertEqual(_deadlines(bulk), [])

    def test_updates_policy_effective_date_is_gated(self) -> None:
        body = "We updated our Terms of Use and Privacy Policy, effective July 27, 2026."
        update = _message(labels=("CATEGORY_UPDATES",), body=body)
        self.assertEqual(_deadlines(update), [])

    def test_gmail_routing_signals_survive_sqlite_round_trip(self) -> None:
        message = _message(
            labels=("INBOX", "CATEGORY_PROMOTIONS"),
            list_unsubscribe="<https://example.com/unsubscribe>",
            body="Final reminder: please respond by July 1, 2026 to keep your account.",
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            db.init_db(paths)
            db.upsert_email_message(paths, message=message, facts=[], ingested_at="2026-06-13T00:00:00Z")

            row = db.list_email_messages(paths)[0]
            self.assertEqual(row["labels"], ["INBOX", "CATEGORY_PROMOTIONS"])
            self.assertEqual(row["list_unsubscribe"], "<https://example.com/unsubscribe>")

            restored = stored_email_messages(paths)[0]
            self.assertEqual(restored.gmail_category, "promotions")
            self.assertTrue(restored.is_bulk)


    def test_promotional_price_is_not_an_amount(self) -> None:
        """A marketing figure ($129 getaway, bonus points) in a Promotions
        email is not money owed and must not become an amount fact."""
        body = "A 3-Night Getaway From $129 Is Waiting For You! Earn 50,000 points."
        promo = _message(labels=("CATEGORY_PROMOTIONS",), body=body)
        self.assertEqual(_kinds(promo, "amount"), [])

    def test_promotional_amount_with_real_bill_survives(self) -> None:
        """A genuine obligation ('balance due') keeps the amount even in a
        promotional-tab message."""
        body = "Account notice: your balance due is $42.50. Please pay to avoid a fee."
        promo = _message(labels=("CATEGORY_PROMOTIONS",), body=body)
        self.assertIn("$42.50", _kinds(promo, "amount"))

    def test_primary_amount_is_untouched(self) -> None:
        body = "A 3-Night Getaway From $129 Is Waiting For You!"
        primary = _message(labels=("INBOX", "CATEGORY_PERSONAL"), body=body)
        self.assertIn("$129", _kinds(primary, "amount"))

    def test_promotional_call_to_action_is_dropped(self) -> None:
        body = "Redeem your points now and enjoy the offer. Shop the sale today."
        promo = _message(labels=("CATEGORY_PROMOTIONS",), body=body)
        self.assertEqual(_kinds(promo, "action"), [])

    def test_promotional_action_with_real_obligation_survives(self) -> None:
        body = "Action required: please pay your bill of $20 by July 1, 2026 to keep service."
        promo = _message(labels=("CATEGORY_PROMOTIONS",), body=body)
        self.assertTrue(_kinds(promo, "action"))


if __name__ == "__main__":
    unittest.main()
