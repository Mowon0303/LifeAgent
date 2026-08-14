"""Date helpers so no test depends on the day it happens to run.

Two complementary tools:

``iso`` / ``us`` / ``long_form``
    Build dates as offsets from the currently pinned "today", in the formats the
    extractor understands. A test that says ``us(+8)`` keeps meaning "eight days
    out" forever; a test that says ``"07/01/2026"`` silently becomes a test about
    an expired deadline.

``BASELINES`` / ``each_baseline``
    Re-run a date-sensitive scenario with the clock pinned to several different
    days — deliberately including one *before* and one *after* the dates this
    suite originally hard-coded, plus a year boundary and the real current day.
    A scenario that only works "this month" fails here instead of in six months.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sentineldesk import clock

# The dates the suite used to hard-code sat between 2026-07-01 and 2026-09-03.
ORIGINAL_FIXTURE_WINDOW = ("2026-07-01", "2026-09-03")

BASELINES: dict[str, str] = {
    # before every date the old fixtures assumed
    "before_original_fixtures": "2026-05-15",
    # after every date the old fixtures assumed
    "after_original_fixtures": "2027-03-02",
    # a deadline four days out lands in the next year
    "year_boundary": "2026-12-29",
    # a leap day, because date arithmetic likes to break there
    "leap_day": "2028-02-29",
}


@contextmanager
def pinned(day: str) -> Iterator[str]:
    """Pin the product clock to ``day`` for the duration of the block."""
    with clock.frozen(day) as today:
        yield today.isoformat()


def each_baseline(include_real_today: bool = True) -> Iterator[tuple[str, str]]:
    """Yield ``(label, day)`` for every baseline, newest information last.

    Use with ``subTest`` so a failure names the day that broke::

        for label, day in each_baseline():
            with self.subTest(baseline=label), pinned(day):
                ...
    """
    for label, day in BASELINES.items():
        yield label, day
    if include_real_today:
        yield "real_today", clock.today_iso()


def iso(offset: int = 0) -> str:
    """``YYYY-MM-DD``, ``offset`` days from the pinned today."""
    return clock.shift_iso(offset)


def us(offset: int = 0) -> str:
    """``MM/DD/YYYY``, the format most US billing mail uses."""
    return _fmt(offset, "%m/%d/%Y")


def long_form(offset: int = 0) -> str:
    """``September 03, 2026``, the format most notices use."""
    return _fmt(offset, "%B %d, %Y")


def _fmt(offset: int, pattern: str) -> str:
    from datetime import date

    return date.fromisoformat(clock.shift_iso(offset)).strftime(pattern)


def timestamp(offset: int = 0, *, time_of_day: str = "09:00:00") -> str:
    """An ISO timestamp ``offset`` days from the pinned today."""
    return f"{iso(offset)}T{time_of_day}+00:00"
