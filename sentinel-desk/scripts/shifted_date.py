"""Print today shifted by N days, and expose it as a GitHub Actions output.

Used by the date-rot guard job to pin the product clock to a day in the future
or the past without writing shell-specific date arithmetic (`date -d` does not
exist on Windows runners).

    python -B scripts/shifted_date.py 365
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta


def main(argv: list[str]) -> int:
    offset = int(argv[1]) if len(argv) > 1 else 0
    day = (date.today() + timedelta(days=offset)).isoformat()
    print(day)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"day={day}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
