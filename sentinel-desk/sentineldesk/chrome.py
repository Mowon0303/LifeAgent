from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from .config import Paths


DEFAULT_PROFILE_MARKERS = [
    "Library/Application Support/Google/Chrome",
    "AppData/Local/Google/Chrome/User Data",
    ".config/google-chrome",
]


def chrome_executable() -> str:
    if platform.system() == "Darwin":
        return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if platform.system() == "Windows":
        return "chrome.exe"
    return "google-chrome"


def looks_like_default_profile(path: Path) -> bool:
    normalized = str(path.expanduser())
    return any(marker in normalized for marker in DEFAULT_PROFILE_MARKERS)


def launch(paths: Paths, *, port: int = 9222, address: str = "127.0.0.1", start_url: str = "about:blank") -> subprocess.Popen:
    if looks_like_default_profile(paths.chrome_profile):
        raise ValueError("Refusing to launch remote debugging against a default Chrome profile.")
    paths.chrome_profile.mkdir(parents=True, exist_ok=True)
    command = [
        chrome_executable(),
        f"--remote-debugging-port={port}",
        f"--remote-debugging-address={address}",
        f"--user-data-dir={paths.chrome_profile}",
        "--no-first-run",
        "--no-default-browser-check",
        start_url,
    ]
    return subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
