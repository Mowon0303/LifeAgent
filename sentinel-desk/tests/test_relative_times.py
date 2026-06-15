from __future__ import annotations

import unittest

from sentineldesk.relative_times import resolve_clock_range, resolve_clock_time


class ResolveClockTimeTests(unittest.TestCase):
    def test_pm_markers_add_twelve(self) -> None:
        self.assertEqual(resolve_clock_time("下午4点开会"), "16:00")  # the slot-eval failure case
        self.assertEqual(resolve_clock_time("晚上8点"), "20:00")
        self.assertEqual(resolve_clock_time("傍晚6点"), "18:00")

    def test_am_markers_keep_the_hour(self) -> None:
        self.assertEqual(resolve_clock_time("上午十点体检"), "10:00")
        self.assertEqual(resolve_clock_time("早上7点"), "07:00")
        self.assertEqual(resolve_clock_time("凌晨3点"), "03:00")

    def test_minutes(self) -> None:
        self.assertEqual(resolve_clock_time("晚上8点半"), "20:30")
        self.assertEqual(resolve_clock_time("下午2点20分"), "14:20")
        self.assertEqual(resolve_clock_time("上午九点十五分"), "09:15")

    def test_noon_and_midnight_edges(self) -> None:
        self.assertEqual(resolve_clock_time("中午吃饭"), "12:00")
        self.assertEqual(resolve_clock_time("中午一点"), "13:00")
        self.assertEqual(resolve_clock_time("晚上12点"), "00:00")
        self.assertEqual(resolve_clock_time("凌晨12点"), "00:00")

    def test_explicit_and_english(self) -> None:
        self.assertEqual(resolve_clock_time("14:00 开会"), "14:00")
        self.assertEqual(resolve_clock_time("meeting at 4pm"), "16:00")
        self.assertEqual(resolve_clock_time("9am standup"), "09:00")
        self.assertEqual(resolve_clock_time("11:30pm call"), "23:30")

    def test_bare_or_no_time_is_left_to_the_model(self) -> None:
        # No AM/PM marker -> genuinely ambiguous (3am vs 3pm); don't guess.
        self.assertEqual(resolve_clock_time("三点开会"), "")
        self.assertEqual(resolve_clock_time("提醒我明天交房租"), "")
        self.assertEqual(resolve_clock_time("把会议加到日历"), "")


class ResolveClockRangeTests(unittest.TestCase):
    def test_range_shares_the_start_marker(self) -> None:
        self.assertEqual(resolve_clock_range("下午2点到3点开会"), ("14:00", "15:00"))
        self.assertEqual(resolve_clock_range("晚上7点到9点"), ("19:00", "21:00"))
        self.assertEqual(resolve_clock_range("上午10点半到11点"), ("10:30", "11:00"))

    def test_range_each_side_can_have_its_own_marker(self) -> None:
        self.assertEqual(resolve_clock_range("下午2点到晚上8点"), ("14:00", "20:00"))

    def test_single_time_returns_empty_end(self) -> None:
        self.assertEqual(resolve_clock_range("晚上8点"), ("20:00", ""))

    def test_unmarked_range_is_left_to_the_model(self) -> None:
        self.assertEqual(resolve_clock_range("三点到四点"), ("", ""))
        self.assertEqual(resolve_clock_range("提醒我明天交房租"), ("", ""))


if __name__ == "__main__":
    unittest.main()
