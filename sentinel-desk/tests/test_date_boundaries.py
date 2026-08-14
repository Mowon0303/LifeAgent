"""Date-boundary behaviour, pinned so it means the same thing on any day.

Covers the rules that used to rot silently as real time moved past the fixture
dates:

* yesterday / today / tomorrow, across a year boundary and a leap day;
* a deadline with no resolvable date;
* a past *unconfirmed* draft stays hidden, a past *confirmed* event stays visible;
* calendar, tasks, the daily summary, and the assistant all agree on "today";
* the synthetic inbox fixture materializes to future deadlines whenever loaded.
"""

from __future__ import annotations

import tempfile
import unittest

from sentineldesk import clock, db
from sentineldesk.agent.graph import answer_question
from sentineldesk.calendar.view import build_calendar_items
from sentineldesk.config import ensure_config, ensure_dirs, get_paths, project_root
from sentineldesk.daily import build_daily_landing_summary
from sentineldesk.email.ingest import ingest_messages, load_fixture_email_json
from sentineldesk.email.models import EmailMessage
from sentineldesk.tasks import list_tasks

from tests.dates import BASELINES, each_baseline, iso, long_form, pinned, timestamp

SAMPLE_EMAILS = project_root() / "fixtures" / "ui" / "sample_emails.json"


def _draft(event_id: str, date_text: str, *, sync_state: str = "local_draft") -> dict:
    return {
        "event_id": event_id,
        "title": f"Deadline {event_id}",
        "date_text": date_text,
        "sync_state": sync_state,
        "status": "draft",
        "confidence": 0.9,
        "source_ids": [f"email:{event_id}"],
    }


class CalendarDateBoundaryTests(unittest.TestCase):
    def test_yesterday_today_tomorrow(self) -> None:
        for label, day in each_baseline():
            with self.subTest(baseline=label), pinned(day):
                items = build_calendar_items(
                    [_draft("yesterday", iso(-1)), _draft("today", iso(0)), _draft("tomorrow", iso(+1))],
                    [],
                )
                # Today is still actionable; yesterday is not.
                self.assertEqual([item["event_id"] for item in items], ["today", "tomorrow"])

    def test_year_boundary_deadline_is_upcoming_not_stale(self) -> None:
        with pinned("2026-12-29"):
            items = build_calendar_items([_draft("new-year", "2027-01-03")], [])
            self.assertEqual([item["date_key"] for item in items], ["2027-01-03"])
        # ... and the same date one week later is behind us.
        with pinned("2027-01-10"):
            self.assertEqual(build_calendar_items([_draft("new-year", "2027-01-03")], []), [])

    def test_leap_day_deadline(self) -> None:
        with pinned("2028-02-28"):
            items = build_calendar_items([_draft("leap", "2028-02-29")], [])
            self.assertEqual([item["date_key"] for item in items], ["2028-02-29"])

    def test_deadline_without_a_resolvable_date_is_never_a_calendar_event(self) -> None:
        for label, day in each_baseline():
            with self.subTest(baseline=label), pinned(day):
                items = build_calendar_items(
                    [_draft("dateless", "within 30 days of the program end date"), _draft("dated", iso(+10))],
                    [],
                )
                self.assertEqual([item["event_id"] for item in items], ["dated"])

    def test_past_unconfirmed_draft_hidden_but_confirmed_history_kept(self) -> None:
        for label, day in each_baseline():
            with self.subTest(baseline=label), pinned(day):
                items = build_calendar_items(
                    [
                        _draft("past-draft", iso(-30)),
                        _draft("past-confirmed", iso(-30), sync_state="ics_exported"),
                        _draft("future-draft", iso(+30)),
                    ],
                    [],
                )
                ids = {item["event_id"] for item in items}
                self.assertNotIn("past-draft", ids, "an expired suggestion is not actionable")
                self.assertIn("past-confirmed", ids, "history the user confirmed stays on the board")
                self.assertIn("future-draft", ids)


class TodayAgreesEverywhereTests(unittest.TestCase):
    """Calendar, tasks, daily summary and the assistant share one notion of today."""

    def _seed(self, paths) -> None:
        ensure_dirs(paths)
        ensure_config(paths)
        db.init_db(paths)
        messages = [
            EmailMessage(
                message_id="m-yesterday",
                thread_id="t-yesterday",
                sender="billing@example.com",
                subject="Expired notice",
                received_at=timestamp(-10),
                body_text=f"Payment was due by {long_form(-1)}.",
            ),
            EmailMessage(
                message_id="m-today",
                thread_id="t-today",
                sender="billing@example.com",
                subject="Due today",
                received_at=timestamp(-10),
                body_text=f"Payment is due by {long_form(0)}.",
            ),
            EmailMessage(
                message_id="m-tomorrow",
                thread_id="t-tomorrow",
                sender="billing@example.com",
                subject="Due tomorrow",
                received_at=timestamp(-10),
                body_text=f"Payment is due by {long_form(+1)}.",
            ),
        ]
        ingest_messages(paths, messages, ingested_at=timestamp(-10))

    def test_all_four_surfaces_agree_on_which_deadlines_are_still_open(self) -> None:
        for label, day in each_baseline():
            with self.subTest(baseline=label), pinned(day), tempfile.TemporaryDirectory() as tmp:
                paths = get_paths(tmp)
                self._seed(paths)

                expected = {iso(0), iso(+1)}

                calendar = build_calendar_items(
                    db.list_calendar_drafts(paths, limit=100), db.list_approval_records(paths, limit=100)
                )
                self.assertEqual({item["date_key"] for item in calendar}, expected, "calendar")

                deadline_tasks = list_tasks(paths, kind="deadline", limit=100)
                self.assertEqual(
                    {task["due_date"] for task in deadline_tasks},
                    {long_form(0), long_form(+1)},
                    "task queue",
                )

                summary = build_daily_landing_summary(paths, record_audit=False)
                self.assertEqual(
                    {item["date_key"] for item in summary["calendar"]["items"]}, expected, "daily summary"
                )

                approved = [dict(item, approval_state="approved") for item in calendar]
                cards = answer_question("最近有什么要处理", calendar=approved).metadata.get("cards")
                self.assertEqual({card["date"] for card in cards}, expected, "assistant overview")

    def test_daily_summary_honours_an_explicit_now(self) -> None:
        """Passing `now` moves the whole summary, not just its timestamp."""
        with pinned(BASELINES["before_original_fixtures"]), tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            self._seed(paths)
            tomorrow = iso(+1)

            # Re-run "as if" it were two days later: both of the previously open
            # deadlines are behind us, so the board and the queue both empty out.
            later = build_daily_landing_summary(paths, now=f"{iso(+2)}T00:00:00+00:00", record_audit=False)
            self.assertEqual(later["calendar"]["items"], [])
            self.assertEqual(
                [task for task in later["tasks"]["queue"] if task["kind"] == "deadline"], []
            )
            self.assertNotIn(tomorrow, {item["date_key"] for item in later["calendar"]["items"]})


class SyntheticInboxStaysActionableTests(unittest.TestCase):
    def test_fixture_deadlines_are_always_in_the_future(self) -> None:
        for label, day in each_baseline():
            with self.subTest(baseline=label), pinned(day), tempfile.TemporaryDirectory() as tmp:
                paths = get_paths(tmp)
                ensure_dirs(paths)
                ensure_config(paths)
                db.init_db(paths)
                messages = load_fixture_email_json(SAMPLE_EMAILS)
                self.assertNotIn("{{today", " ".join(m.body_text for m in messages))
                ingest_messages(paths, messages)

                items = build_calendar_items(db.list_calendar_drafts(paths, limit=100), [])
                self.assertEqual(len(items), 3, "all three fixture deadlines stay visible")
                self.assertTrue(all(item["date_key"] >= iso(0) for item in items), items)

    def test_render_date_tokens_supports_offsets_and_formats(self) -> None:
        with pinned("2026-08-14"):
            self.assertEqual(clock.render_date_tokens("{{today}}"), "2026-08-14")
            self.assertEqual(clock.render_date_tokens("{{today+8}}"), "2026-08-22")
            self.assertEqual(clock.render_date_tokens("{{today-6}}"), "2026-08-08")
            self.assertEqual(clock.render_date_tokens("{{today+8|%m/%d/%Y}}"), "08/22/2026")
            self.assertEqual(clock.render_date_tokens("no tokens here"), "no tokens here")


class ClockOverrideTests(unittest.TestCase):
    def test_frozen_clock_is_restored_and_exported_to_subprocesses(self) -> None:
        import os

        before = clock.today_iso()
        outer_env = os.environ.get(clock.NOW_ENV_VAR)
        with pinned("2030-06-01") as today:
            self.assertEqual(today, "2030-06-01")
            self.assertEqual(clock.today_iso(), "2030-06-01")
            self.assertEqual(os.environ[clock.NOW_ENV_VAR], "2030-06-01")
        self.assertEqual(clock.today_iso(), before)
        # Restored exactly as it was — including when the whole suite is itself
        # running under a pinned SENTINELDESK_NOW.
        self.assertEqual(os.environ.get(clock.NOW_ENV_VAR), outer_env)

    def test_malformed_override_falls_back_to_the_real_clock(self) -> None:
        """A bad override must not silently invent some other day."""
        previous = clock.set_now("not-a-date")
        try:
            self.assertRegex(clock.today_iso(), r"^\d{4}-\d{2}-\d{2}$")
        finally:
            clock.set_now(previous or None)


if __name__ == "__main__":
    unittest.main()
