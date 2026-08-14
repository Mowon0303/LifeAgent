from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .config import Paths


# Attaching a remote debugger to the user's everyday Chrome profile would expose
# every logged-in session in it, so the default profile is refused on all three
# platforms. Markers are matched with separators normalized to "/" and casing
# folded, because the same profile is spelled differently per platform:
#
#   macOS    ~/Library/Application Support/Google/Chrome
#   Windows  C:\Users\<name>\AppData\Local\Google\Chrome\User Data
#   Linux    ~/.config/google-chrome
DEFAULT_PROFILE_MARKERS = [
    "library/application support/google/chrome",
    "library/application support/chromium",
    "appdata/local/google/chrome/user data",
    "appdata/local/chromium/user data",
    "appdata/roaming/google/chrome/user data",
    ".config/google-chrome",
    ".config/chromium",
]


def chrome_executable() -> str:
    # sys.platform, not platform.system(): the latter shells out to `cmd /c ver`
    # on Windows, which is both slower and fragile inside sandboxed runs.
    if sys.platform == "darwin":
        return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if sys.platform.startswith("win"):
        return "chrome.exe"
    return "google-chrome"


def looks_like_default_profile(path: Path) -> bool:
    normalized = str(path.expanduser()).replace("\\", "/").lower()
    return any(marker in normalized for marker in DEFAULT_PROFILE_MARKERS)


def _detach_kwargs() -> dict[str, object]:
    """Keep Chrome off our process group so it survives and never steals signals.

    `start_new_session` is a POSIX-only Popen argument; Windows silently ignores
    it, so pass the real equivalent there instead of pretending it applied.
    """
    if sys.platform.startswith("win"):
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


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
        **_detach_kwargs(),
    )
