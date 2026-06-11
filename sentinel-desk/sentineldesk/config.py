from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


APP_HOME_ENV = "SENTINEL_HOME"


DEFAULT_CONFIG = """# SentinelDesk local configuration
[browser]
debug_address = "127.0.0.1"
debug_port = 9222

[policy]
fail_loud = true
semantic_llm = "changes-only"
high_stakes_default = true

[vertical.opt]
label = "OPT/USCIS/OIS"
fail_on_unknown_status = true
meaningful_change_level = "critical"
text_change_level = "info"

[vertical.appointment]
label = "Appointment slot"
fail_on_unknown_status = true
meaningful_change_level = "critical"
text_change_level = "info"

[model]
provider = "ollama"
base_url = "http://127.0.0.1:11434"
model = "llama3.2:latest"
privacy = "local-first"
structured_output = true
"""


@dataclass(frozen=True)
class Paths:
    home: Path
    config: Path
    database: Path
    artifacts: Path
    demo: Path
    chrome_profile: Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_paths(home: str | Path | None = None) -> Paths:
    root = Path(home or os.environ.get(APP_HOME_ENV, "~/.sentineldesk")).expanduser().resolve()
    return Paths(
        home=root,
        config=root / "config.toml",
        database=root / "sentineldesk.sqlite3",
        artifacts=root / "artifacts",
        demo=root / "demo",
        chrome_profile=root / "chrome-profile",
    )


def ensure_dirs(paths: Paths) -> None:
    for path in [paths.home, paths.artifacts, paths.demo, paths.chrome_profile]:
        path.mkdir(parents=True, exist_ok=True)


def ensure_config(paths: Paths) -> bool:
    if paths.config.exists():
        return False
    paths.config.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return True


def seed_demo_fixtures(paths: Paths) -> int:
    source = project_root() / "fixtures" / "portals"
    if not source.exists():
        return 0
    paths.demo.mkdir(parents=True, exist_ok=True)
    copied = 0
    for item in source.glob("*.html"):
        destination = paths.demo / item.name
        shutil.copyfile(item, destination)
        copied += 1
    return copied


def file_url(path: Path) -> str:
    return path.resolve().as_uri()
