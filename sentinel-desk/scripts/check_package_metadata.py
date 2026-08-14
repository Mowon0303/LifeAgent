"""Assert the packaging metadata still describes this project.

Lives in a file rather than a CI heredoc so it runs identically on Windows,
where there is no Bash to interpret one.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert project["name"] == "sentineldesk", project["name"]
    assert "email-first" in project["description"].lower(), project["description"]
    assert project["requires-python"].startswith(">=3.11"), project["requires-python"]
    print(f"package metadata ok: {project['name']} {project['version']} ({project['requires-python']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
