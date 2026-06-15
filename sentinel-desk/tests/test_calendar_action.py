from __future__ import annotations

import unittest
from types import SimpleNamespace

from sentineldesk.agent.graph import answer_question
from sentineldesk.agent.graph.calendar_action import (
    _calendar_action_answer,
    _classify_calendar_action,
    _extract_slots,
)
from sentineldesk.agent.llm import ModelCallResult
from sentineldesk.agent.schemas import Intent
from sentineldesk.email.models import EmailMessage


class FakeRegistry:
    def __init__(self, documents: list) -> None:
        self.documents = documents

    def assert_can_call(self, name: str) -> SimpleNamespace:
        return SimpleNamespace(handler=object())

    def call(self, name: str, **kwargs) -> dict:
        return {"documents": self.documents}


def _email(message_id: str, subject: str, body: str) -> EmailMessage:
    return EmailMessage(
        message_id=message_id, thread_id="t-" + message_id, sender="ops@example.com",
        subject=subject, received_at="2026-06-01T00:00:00Z", body_text=body,
    )

EVENTS = [
    {"event_id": "e1", "title": "牙医预约", "date_key": "2026-06-25", "start_time": "14:00"},
    {"event_id": "e2", "title": "团队同步会", "date_key": "2026-07-01", "start_time": "10:00"},
    {"event_id": "e3", "title": "导师组会", "date_key": "2026-07-03"},
]


class FakeChat:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    def chat(self, *, system: str, user: str) -> ModelCallResult:
        return ModelCallResult(text=self.reply, prompt_tokens=1, completion_tokens=1, duration_ms=1)


class CalendarActionTests(unittest.TestCase):
    def test_proposes_an_event_from_a_natural_request(self) -> None:
        client = FakeChat('{"title":"牙医预约","date":"2026-06-20","start_time":"15:00","end_time":""}')
        answer = answer_question("把6月20号下午3点的牙医预约加到日历", chat_client=client)
        self.assertEqual(answer.intent, Intent.CALENDAR_ACTION)
        self.assertTrue(answer.requires_confirmation)  # nothing is written until the user confirms
        event = answer.metadata.get("proposed_event")
        self.assertEqual(event["title"], "牙医预约")
        self.assertEqual(event["date"], "2026-06-20")
        self.assertEqual(event["start_time"], "15:00")

    def test_json_wrapped_in_prose_is_still_parsed(self) -> None:
        client = FakeChat('好的，这是事件：\n{"title":"团队会","date":"2026-07-01","start_time":"","end_time":""}\n要确认吗')
        answer = answer_question("帮我把7月1号团队会加日历", chat_client=client)
        self.assertEqual(answer.metadata.get("proposed_event")["date"], "2026-07-01")

    def test_no_clear_event_asks_instead_of_creating(self) -> None:
        answer = answer_question("帮我加个日历", chat_client=FakeChat("{}"))
        self.assertEqual(answer.intent, Intent.CALENDAR_ACTION)
        self.assertIsNone((answer.metadata or {}).get("proposed_event"))
        self.assertIn("哪一天", answer.answer)

    def test_unparseable_date_is_not_proposed(self) -> None:
        # The model echoed a relative phrase it couldn't resolve — don't guess a date.
        # No resolvable relative phrase, and the model's date is junk -> don't guess.
        client = FakeChat('{"title":"交报告","date":"sometime soon","start_time":"","end_time":""}')
        answer = answer_question("提醒我尽快把报告交了", chat_client=client)
        self.assertIsNone((answer.metadata or {}).get("proposed_event"))

    def test_no_model_falls_back_to_a_clarify_not_a_crash(self) -> None:
        answer = answer_question("把会议加到日历", chat_client=None)
        self.assertEqual(answer.intent, Intent.CALENDAR_ACTION)
        self.assertIsNone((answer.metadata or {}).get("proposed_event"))

    def test_invalid_time_is_dropped_but_the_event_still_proposed(self) -> None:
        client = FakeChat('{"title":"x","date":"2026-08-01","start_time":"25:99","end_time":""}')
        answer = answer_question("加个8月1号的x到日历", chat_client=client)
        self.assertEqual(answer.metadata.get("proposed_event")["start_time"], "")

    def test_resolver_overrides_a_wrong_model_date(self) -> None:
        # The model put a wrong date for "下周三" (6-20); the deterministic resolver
        # wins (6-17 from Sunday 2026-06-14). Title/time from the model are kept.
        client = FakeChat('{"title":"组会","date":"2026-06-20","start_time":"10:00","end_time":""}')
        slots = _extract_slots("下周三上午十点开组会", client=client, today="2026-06-14")
        self.assertEqual(slots["date"], "2026-06-17")
        self.assertEqual(slots["title"], "组会")
        self.assertEqual(slots["start_time"], "10:00")

    def test_title_is_salvaged_when_model_abstains_on_a_relative_request(self) -> None:
        # qwen returns "{}" for "三天后和导师开会"; we have the resolved date, so derive
        # the title from the question instead of dropping the whole request.
        slots = _extract_slots("三天后和导师开会", client=FakeChat("{}"), today="2026-06-14")
        self.assertEqual(slots["date"], "2026-06-17")
        self.assertIn("导师", slots["title"])


class CalendarEditDeleteTests(unittest.TestCase):
    def test_classify_create_edit_delete(self) -> None:
        self.assertEqual(_classify_calendar_action("把6月20号牙医加到日历"), "create")
        self.assertEqual(_classify_calendar_action("把牙医那条改到周四"), "edit")
        self.assertEqual(_classify_calendar_action("删掉下周的组会"), "delete")

    def test_delete_resolves_the_target_and_requires_confirmation(self) -> None:
        answer = _calendar_action_answer(
            "删掉牙医那条", client=FakeChat('{"targets":[1],"changes":{}}'),
            today="2026-06-14", events=EVENTS,
        )
        self.assertTrue(answer.requires_confirmation)  # a delete is a write — confirm first
        change = answer.metadata["proposed_change"]
        self.assertEqual(change["action"], "delete")
        self.assertEqual(change["target"]["event_id"], "e1")

    def test_edit_resolves_target_and_changes(self) -> None:
        answer = _calendar_action_answer(
            "把团队同步会改到7月2号", client=FakeChat('{"targets":[2],"changes":{"date":"2026-07-02"}}'),
            today="2026-06-14", events=EVENTS,
        )
        change = answer.metadata["proposed_change"]
        self.assertEqual(change["action"], "edit")
        self.assertEqual(change["target"]["event_id"], "e2")
        self.assertEqual(change["changes"]["date"], "2026-07-02")

    def test_edit_relative_date_is_resolved_deterministically(self) -> None:
        # The model echoed a wrong date for "下周三"; the resolver overrides it (6-17).
        answer = _calendar_action_answer(
            "把牙医改到下周三", client=FakeChat('{"targets":[1],"changes":{"date":"2026-06-20"}}'),
            today="2026-06-14", events=EVENTS,
        )
        self.assertEqual(answer.metadata["proposed_change"]["changes"]["date"], "2026-06-17")

    def test_top3_candidates_surface_for_the_not_that_one_fallback(self) -> None:
        answer = _calendar_action_answer(
            "删掉那个会", client=FakeChat('{"targets":[2,3,1],"changes":{}}'),
            today="2026-06-14", events=EVENTS,
        )
        change = answer.metadata["proposed_change"]
        self.assertEqual(change["target"]["event_id"], "e2")           # top-1
        self.assertEqual([c["event_id"] for c in change["candidates"]], ["e2", "e3", "e1"])

    def test_no_events_to_edit(self) -> None:
        answer = _calendar_action_answer("删掉牙医", client=FakeChat("{}"), today="2026-06-14", events=[])
        self.assertIsNone((answer.metadata or {}).get("proposed_change"))
        self.assertIn("还没有", answer.answer)

    def test_unmatched_target_asks_instead_of_guessing(self) -> None:
        answer = _calendar_action_answer(
            "删掉买菜", client=FakeChat('{"targets":[],"changes":{}}'),
            today="2026-06-14", events=EVENTS,
        )
        self.assertIsNone((answer.metadata or {}).get("proposed_change"))
        self.assertIn("没找到", answer.answer)


class CalendarFromEmailTests(unittest.TestCase):
    def test_create_from_a_referenced_email_uses_the_emails_deadline(self) -> None:
        msg = _email("m1", "USCIS Case Update", "Please submit your documents by 07/01/2026 — this deadline is firm.")
        registry = FakeRegistry([{"source_id": msg.source_id, "metadata": {"subject": "USCIS Case Update"}, "text": msg.body_text}])
        answer = _calendar_action_answer(
            "把 USCIS 那封的截止加到日历", client=None, today="2026-06-14",
            events=[], registry=registry, messages=[msg],
        )
        event = answer.metadata["proposed_event"]
        self.assertEqual(event["date"], "2026-07-01")   # the email's date, not a model guess
        self.assertIn("USCIS", event["title"])
        self.assertTrue(answer.requires_confirmation)
        self.assertEqual(answer.metadata.get("source_email"), msg.source_id)

    def test_no_matching_email_asks(self) -> None:
        answer = _calendar_action_answer(
            "把那封邮件的截止加日历", client=None, today="2026-06-14",
            events=[], registry=FakeRegistry([]), messages=[],
        )
        self.assertIsNone((answer.metadata or {}).get("proposed_event"))
        self.assertIn("没找到", answer.answer)

    def test_referenced_email_without_a_deadline_asks_for_a_date(self) -> None:
        msg = _email("m2", "Newsletter", "Thanks for subscribing to our weekly roundup.")
        registry = FakeRegistry([{"source_id": msg.source_id, "metadata": {"subject": "Newsletter"}, "text": msg.body_text}])
        answer = _calendar_action_answer(
            "把这封邮件的截止加日历", client=None, today="2026-06-14",
            events=[], registry=registry, messages=[msg],
        )
        self.assertIsNone((answer.metadata or {}).get("proposed_event"))
        self.assertIn("没找到明确的截止", answer.answer)


if __name__ == "__main__":
    unittest.main()
