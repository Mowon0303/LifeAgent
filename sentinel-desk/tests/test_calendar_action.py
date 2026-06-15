from __future__ import annotations

import unittest

from sentineldesk.agent.graph import answer_question
from sentineldesk.agent.llm import ModelCallResult
from sentineldesk.agent.schemas import Intent


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
        client = FakeChat('{"title":"交报告","date":"next Friday","start_time":"","end_time":""}')
        answer = answer_question("提醒我下周五交报告", chat_client=client)
        self.assertIsNone((answer.metadata or {}).get("proposed_event"))

    def test_no_model_falls_back_to_a_clarify_not_a_crash(self) -> None:
        answer = answer_question("把会议加到日历", chat_client=None)
        self.assertEqual(answer.intent, Intent.CALENDAR_ACTION)
        self.assertIsNone((answer.metadata or {}).get("proposed_event"))

    def test_invalid_time_is_dropped_but_the_event_still_proposed(self) -> None:
        client = FakeChat('{"title":"x","date":"2026-08-01","start_time":"25:99","end_time":""}')
        answer = answer_question("加个8月1号的x到日历", chat_client=client)
        self.assertEqual(answer.metadata.get("proposed_event")["start_time"], "")


if __name__ == "__main__":
    unittest.main()
