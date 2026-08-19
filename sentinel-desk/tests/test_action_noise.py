"""An imperative verb is not a task.

Real mail is full of instructions nobody is being asked to act on, and the first
live review put all three kinds into the queue:

* negated   -- "please don't reply to this" was extracted as a "reply" task,
               telling the user to do the exact thing the sender forbade;
* conditional on a non-event -- "if you didn't make this payment, contact us";
* boilerplate -- trademark footers and standing advice, reprinted every time.

The line these tests hold is between those and the instructions that *are* tasks,
because the cheap fix (suppress anything that looks like a footer) costs recall on
real obligations.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sentineldesk import db
from sentineldesk.config import get_paths
from sentineldesk.email.extract import extract_email_facts
from sentineldesk.email.models import EmailMessage
from sentineldesk.tasks import list_tasks

from tests.dates import timestamp


def _message(message_id: str, body: str, *, sender: str = "alerts@bank.example") -> EmailMessage:
    return EmailMessage(
        message_id=message_id, thread_id=f"t-{message_id}", sender=sender,
        subject="Notice", received_at=timestamp(-1), body_text=body,
    )


def _actions(body: str) -> list[str]:
    return [f.value for f in extract_email_facts(_message("m", body)) if f.kind == "action"]


class SuppressedInstructionTests(unittest.TestCase):
    NEGATED = [
        "Please don't reply to this automatically generated service email.",
        "Do not reply to this message.",
        "Tripalink Move-out Notice (DON'T REPLY) Dear Valued Tenant",
        "There is no need to contact us about this.",
    ]
    CONDITIONAL_ON_NON_EVENT = [
        "If you didn't make this payment, contact us right away.",
        "If you did not authorize this transfer, call the number on your card.",
        "If this wasn't you, verify your identity now.",
        "If you received this in error, contact the sender.",
    ]
    BOILERPLATE = [
        "Remember: Always independently confirm transfer instructions in person.",
        "contact us Zelle and the Zelle related marks are wholly owned by Early Warning",
        "or reply directly to this email for assistance from the support team!",
    ]

    def test_a_negated_instruction_is_never_a_task(self) -> None:
        """The worst failure mode: telling the user to do what the email forbade."""
        for body in self.NEGATED:
            with self.subTest(body=body):
                self.assertEqual(_actions(body), [], body)

    def test_an_instruction_conditional_on_a_non_event_is_not_a_task(self) -> None:
        for body in self.CONDITIONAL_ON_NON_EVENT:
            with self.subTest(body=body):
                self.assertEqual(_actions(body), [], body)

    def test_footer_and_standing_advice_are_not_tasks(self) -> None:
        for body in self.BOILERPLATE:
            with self.subTest(body=body):
                self.assertEqual(_actions(body), [], body)


class PreservedInstructionTests(unittest.TestCase):
    REAL = [
        "Please update your payment details with us ASAP to avoid a lapse.",
        "You must submit the requested documents by September 3, 2026.",
        "Please schedule your appointment before the end of the month.",
        "Your policy expires soon. Renew your coverage to stay insured.",
        "Action required: verify your identity to keep your account active.",
    ]
    # Same grammatical shape as the suppressed conditionals, opposite meaning: a
    # right the user may want to exercise, not a report path for something that
    # did not happen. The golden set caught a broader pattern swallowing these.
    OPINION_CONDITIONALS = [
        "If you believe this charge is incorrect, you must dispute it before August 1, 2026.",
        "If you believe a grade is incorrect, contact the course instructor.",
    ]

    def test_real_instructions_survive(self) -> None:
        for body in self.REAL:
            with self.subTest(body=body):
                self.assertTrue(_actions(body), body)

    def test_opinion_conditionals_are_still_tasks(self) -> None:
        for body in self.OPINION_CONDITIONALS:
            with self.subTest(body=body):
                self.assertTrue(_actions(body), body)


class RepeatedBoilerplateTests(unittest.TestCase):
    """The same line, from the same sender, in message after message."""

    def _tasks(self, senders: list[str], body: str) -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(Path(tmp))
            db.init_db(paths)
            for index, sender in enumerate(senders):
                message = _message(f"m{index}", body, sender=sender)
                db.upsert_email_message(
                    paths, message=message,
                    facts=extract_email_facts(message), ingested_at=timestamp(-1),
                )
            return [t for t in list_tasks(paths, limit=50) if t["kind"] == "action"]

    BODY = "Questions? Contact Anthropic Support."

    def test_a_line_repeated_across_messages_is_demoted(self) -> None:
        tasks = self._tasks(["no-reply@mail.example", "no-reply@mail.example"], self.BODY)
        self.assertEqual(len(tasks), 2)
        for task in tasks:
            self.assertTrue(task.get("boilerplate"), task["value"])
            self.assertIn("repeated_boilerplate", task["priority_reasons"])
            self.assertEqual(task["priority_band"], "low")

    def test_randomized_sender_local_parts_do_not_defeat_it(self) -> None:
        """Transactional senders vary the local part per message; the domain does not."""
        tasks = self._tasks(
            ["no-reply-mvsfpoe6@mail.example", "no-reply-zmivyvtb@mail.example"], self.BODY
        )
        self.assertEqual(len(tasks), 2)
        self.assertTrue(all(t.get("boilerplate") for t in tasks))

    def test_a_line_sent_once_is_left_alone(self) -> None:
        tasks = self._tasks(["no-reply@mail.example"], self.BODY)
        self.assertEqual(len(tasks), 1)
        self.assertFalse(tasks[0].get("boilerplate"))
        self.assertNotIn("repeated_boilerplate", tasks[0]["priority_reasons"])

    def test_different_senders_saying_the_same_thing_are_not_boilerplate(self) -> None:
        tasks = self._tasks(["a@one.example", "b@two.example"], self.BODY)
        self.assertTrue(tasks)
        self.assertFalse(any(t.get("boilerplate") for t in tasks))

    def test_repeated_items_stay_in_the_queue(self) -> None:
        """Demoted, not dropped: two real reminders would look the same."""
        tasks = self._tasks(["no-reply@mail.example", "no-reply@mail.example"], self.BODY)
        self.assertEqual(len(tasks), 2)


if __name__ == "__main__":
    unittest.main()
