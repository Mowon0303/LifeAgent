from __future__ import annotations

import unittest

from sentineldesk.relative_dates import resolve_relative_date

TODAY = "2026-06-14"  # a Sunday — the anchor the agent eval uses


class RelativeDateTests(unittest.TestCase):
    def test_fixed_day_offsets(self) -> None:
        self.assertEqual(resolve_relative_date("今天交报告", TODAY), "2026-06-14")
        self.assertEqual(resolve_relative_date("明天交房租", TODAY), "2026-06-15")
        self.assertEqual(resolve_relative_date("后天上午十点体检", TODAY), "2026-06-16")
        self.assertEqual(resolve_relative_date("大后天面试", TODAY), "2026-06-17")

    def test_n_days_chinese_and_digit(self) -> None:
        self.assertEqual(resolve_relative_date("三天后和导师开会", TODAY), "2026-06-17")
        self.assertEqual(resolve_relative_date("5天后交材料", TODAY), "2026-06-19")
        self.assertEqual(resolve_relative_date("十天后到期", TODAY), "2026-06-24")
        self.assertEqual(resolve_relative_date("过十五天复诊", TODAY), "2026-06-29")

    def test_next_week_weekday(self) -> None:
        # the bug the eval caught: 下周三 from Sunday 6-14 is 6-17, not 6-20
        self.assertEqual(resolve_relative_date("下周三上午十点开组会", TODAY), "2026-06-17")
        self.assertEqual(resolve_relative_date("下周一交表", TODAY), "2026-06-15")
        self.assertEqual(resolve_relative_date("下星期五聚餐", TODAY), "2026-06-19")

    def test_this_week_weekday(self) -> None:
        # "本周X / 这周X" is literal — this week's weekday, even if already past on Sunday.
        self.assertEqual(resolve_relative_date("本周五截止", TODAY), "2026-06-12")
        self.assertEqual(resolve_relative_date("这周三开会", TODAY), "2026-06-10")

    def test_bare_weekday_is_the_upcoming_one(self) -> None:
        self.assertEqual(resolve_relative_date("周三开会", TODAY), "2026-06-17")
        self.assertEqual(resolve_relative_date("周日休息", TODAY), "2026-06-21")  # not today

    def test_english(self) -> None:
        self.assertEqual(resolve_relative_date("dentist tomorrow", TODAY), "2026-06-15")
        self.assertEqual(resolve_relative_date("meeting next Friday", TODAY), "2026-06-19")
        self.assertEqual(resolve_relative_date("review in 3 days", TODAY), "2026-06-17")

    def test_no_relative_phrase_returns_empty(self) -> None:
        self.assertEqual(resolve_relative_date("6月20号下午3点牙医", TODAY), "")
        self.assertEqual(resolve_relative_date("提醒我 2026-09-09 提交材料", TODAY), "")
        self.assertEqual(resolve_relative_date("把这个加到日历", TODAY), "")

    def test_bad_today_is_safe(self) -> None:
        self.assertEqual(resolve_relative_date("明天", "not-a-date"), "")


if __name__ == "__main__":
    unittest.main()
