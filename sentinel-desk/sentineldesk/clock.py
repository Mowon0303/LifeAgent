"""Single source of "now" for the whole product.

Every date-sensitive decision — which deadlines are still actionable, which
calendar drafts are stale suggestions, what "today" means in an assistant
answer — resolves through this module. Calendar, tasks, the daily summary and
the assistant therefore cannot drift apart about which day it is.

The clock is overridable so tests and CI can pin a date instead of silently
depending on the day they happen to run. Production never sets an override:
the fallback is always the real UTC clock, so a deadline that really has passed
really is filtered.

Override precedence:

1. an in-process override set by :func:`set_now` / :func:`frozen`
2. the ``SENTINELDESK_NOW`` environment variable (survives into subprocesses,
   which is how the CLI-level tests and the scheduled CI job pin a date)
3. the real UTC clock
"""

from __future__ import annotations

import contextlib
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Iterator

NOW_ENV_VAR = "SENTINELDESK_NOW"

_override: str = ""

# {{today}}, {{today+14}}, {{today-6}}, {{today+52|%B %d, %Y}}
_DATE_TOKEN_RE = re.compile(r"\{\{\s*today\s*([+-]\s*\d+)?\s*(?:\|\s*([^}]*?)\s*)?\}\}")


def _parse_iso(value: str) -> datetime:
    text = str(value).strip()
    if not text:
        raise ValueError("empty timestamp")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    if len(text) == 10:  # a bare YYYY-MM-DD pins midnight UTC
        text += "T00:00:00+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def now() -> datetime:
    """The current UTC moment, honouring any test/CI override."""
    for candidate in (_override, os.environ.get(NOW_ENV_VAR, "")):
        if not candidate:
            continue
        try:
            return _parse_iso(candidate)
        except ValueError:
            # A malformed override must not silently become "some other day":
            # fall through to the real clock rather than inventing a date.
            continue
    return datetime.now(timezone.utc)


def utc_now() -> str:
    """Second-resolution ISO-8601 UTC timestamp."""
    return now().replace(microsecond=0).isoformat()


def today() -> date:
    return now().date()


def today_iso() -> str:
    return today().isoformat()


def shift_iso(days: int, *, base: str | date | None = None) -> str:
    """``today`` (or ``base``) moved by ``days``, as ``YYYY-MM-DD``."""
    if base is None:
        anchor = today()
    elif isinstance(base, date):
        anchor = base
    else:
        anchor = _parse_iso(str(base)).date()
    return (anchor + timedelta(days=days)).isoformat()


def set_now(value: str | date | datetime | None) -> str:
    """Pin the clock (tests/CI only). Returns the previous override."""
    global _override
    previous = _override
    if value is None:
        _override = ""
    elif isinstance(value, datetime):
        _override = value.isoformat()
    elif isinstance(value, date):
        _override = value.isoformat()
    else:
        _override = str(value)
    return previous


@contextlib.contextmanager
def frozen(value: str | date | datetime) -> Iterator[date]:
    """Run a block with "now" pinned to ``value``.

    Also exports ``SENTINELDESK_NOW`` for the duration so subprocesses and CLI
    entry points launched inside the block see the same day.
    """
    previous_override = set_now(value)
    previous_env = os.environ.get(NOW_ENV_VAR)
    os.environ[NOW_ENV_VAR] = _override
    try:
        yield today()
    finally:
        set_now(previous_override or None)
        if previous_env is None:
            os.environ.pop(NOW_ENV_VAR, None)
        else:
            os.environ[NOW_ENV_VAR] = previous_env


def render_date_tokens(text: str, *, base: date | None = None) -> str:
    """Materialize ``{{today±N}}`` tokens in synthetic fixture text.

    Demo and acceptance fixtures describe their dates as offsets from "today"
    so the synthetic inbox stays actionable no matter when it is loaded. A
    literal date in a fixture rots; an offset does not.

    ``{{today+14}}``            -> 2026-08-27
    ``{{today-6}}``             -> 2026-08-07
    ``{{today+14|%m/%d/%Y}}``   -> 08/27/2026
    """
    if "{{" not in text:
        return text
    anchor = base or today()

    def _replace(match: re.Match[str]) -> str:
        offset = int((match.group(1) or "0").replace(" ", ""))
        resolved = anchor + timedelta(days=offset)
        fmt = match.group(2)
        return resolved.strftime(fmt) if fmt else resolved.isoformat()

    return _DATE_TOKEN_RE.sub(_replace, text)
