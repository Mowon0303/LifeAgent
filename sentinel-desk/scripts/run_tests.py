"""Run the unittest suite and report, loudly, whether it really ran.

`unittest discover` exits 0 when it collects nothing, and reports an import
failure as a single failing "test" that is easy to miss in a long log. Both look
like a green build at a glance. This wrapper makes the outcome explicit:

* prints the total number of tests actually run;
* fails if any test module failed to import;
* fails if fewer than ``--min-tests`` ran, which catches a broken discovery
  path that would otherwise quietly shrink the suite.

Usage::

    python -B scripts/run_tests.py                 # the whole suite
    python -B scripts/run_tests.py --now 2027-03-02  # pinned to a future day
"""

from __future__ import annotations

import argparse
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# A floor, not an exact count: it only has to be high enough that a collapsed or
# half-collected suite trips it. Raise it when the suite grows substantially.
DEFAULT_MIN_TESTS = 400
MAX_SUMMARY_CASES = 20
MAX_SUMMARY_TRACEBACK_CHARS = 3000


def _failed_imports(suite: unittest.TestSuite) -> list[str]:
    names: list[str] = []
    for test in _flatten(suite):
        if type(test).__module__ == "unittest.loader":
            names.append(test.id())
    return names


def _flatten(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


def _write_step_summary(result: unittest.TestResult, *, broken: list[str], today: str) -> None:
    """Publish the outcome to the GitHub job summary.

    Actions logs need `actions:read` to fetch even on a public repository, but the
    job summary is exposed through the check-run output, which anyone can read. A
    failure that only exists in the log is a failure nobody outside the repo can
    diagnose, so the counts and the actual tracebacks go here too.
    """
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    status = "passed" if result.wasSuccessful() and not broken else "FAILED"
    lines = [
        f"### Unit tests: {status}",
        "",
        f"- platform: `{sys.platform}`, python `{sys.version.split()[0]}`",
        f"- product clock (today): `{today}`",
        f"- tests run: **{result.testsRun}**, failures: **{len(result.failures)}**, "
        f"errors: **{len(result.errors)}**, skipped: {len(result.skipped)}",
        "",
    ]
    if broken:
        lines += ["**Test modules that failed to import:**", ""]
        lines += [f"- `{name}`" for name in broken] + [""]

    problems = [("FAIL", case, tb) for case, tb in result.failures]
    problems += [("ERROR", case, tb) for case, tb in result.errors]
    for kind, case, traceback_text in problems[:MAX_SUMMARY_CASES]:
        lines += [
            f"<details><summary>{kind}: {case.id()}</summary>",
            "",
            "```",
            traceback_text.strip()[:MAX_SUMMARY_TRACEBACK_CHARS],
            "```",
            "",
            "</details>",
            "",
        ]
    if len(problems) > MAX_SUMMARY_CASES:
        lines.append(f"_...and {len(problems) - MAX_SUMMARY_CASES} more; see the full log._")

    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-dir", default="tests")
    parser.add_argument("--min-tests", type=int, default=DEFAULT_MIN_TESTS)
    parser.add_argument(
        "--now",
        help="Pin the product clock (SENTINELDESK_NOW) to this date, e.g. 2027-03-02",
    )
    parser.add_argument("--verbosity", type=int, default=1)
    args = parser.parse_args(argv)

    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    if args.now:
        os.environ["SENTINELDESK_NOW"] = args.now

    from sentineldesk import clock  # imported after the override is in place

    print(f"python: {sys.version.split()[0]} on {sys.platform}")
    print(f"today (product clock): {clock.today_iso()}")
    print(f"discovering tests in: {args.start_dir}")

    suite = unittest.defaultTestLoader.discover(args.start_dir)
    broken = _failed_imports(suite)
    if broken:
        print(f"::error::{len(broken)} test module(s) failed to import: {', '.join(broken)}")

    result = unittest.TextTestRunner(verbosity=args.verbosity).run(suite)

    print("-" * 70)
    print(f"tests run:      {result.testsRun}")
    print(f"failures:       {len(result.failures)}")
    print(f"errors:         {len(result.errors)}")
    print(f"skipped:        {len(result.skipped)}")
    print(f"expected fails: {len(result.expectedFailures)}")
    print(f"product clock:  {clock.today_iso()}")

    _write_step_summary(result, broken=broken, today=clock.today_iso())

    if broken:
        return 1
    if result.testsRun < args.min_tests:
        print(
            f"::error::only {result.testsRun} tests ran, expected at least {args.min_tests}. "
            "Discovery is probably broken."
        )
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
