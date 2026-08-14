from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sentineldesk.chrome import launch, looks_like_default_profile
from sentineldesk.config import Paths, get_paths


class ChromeTests(unittest.TestCase):
    def test_launch_uses_dedicated_profile_and_start_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            with patch("sentineldesk.chrome.subprocess.Popen", return_value=object()) as popen:
                process = launch(paths, port=9333, address="127.0.0.1")

        self.assertIsNotNone(process)
        command = popen.call_args.args[0]
        kwargs = popen.call_args.kwargs
        self.assertIn("--remote-debugging-port=9333", command)
        self.assertIn(f"--user-data-dir={paths.chrome_profile}", command)
        self.assertEqual(command[-1], "about:blank")
        self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
        # Detachment is expressed with the argument that actually works on this
        # platform — start_new_session is silently ignored on Windows.
        if sys.platform.startswith("win"):
            self.assertEqual(kwargs["creationflags"], subprocess.CREATE_NEW_PROCESS_GROUP)
            self.assertNotIn("start_new_session", kwargs)
        else:
            self.assertTrue(kwargs["start_new_session"])
            self.assertNotIn("creationflags", kwargs)


class DefaultProfileGuardTests(unittest.TestCase):
    """The default profile must be refused however the platform spells it."""

    DEFAULT_PROFILES = {
        "macos": "/Users/someone/Library/Application Support/Google/Chrome/Profile 1",
        "macos_chromium": "/Users/someone/Library/Application Support/Chromium/Default",
        "windows": r"C:\Users\someone\AppData\Local\Google\Chrome\User Data",
        "windows_profile": r"C:\Users\someone\AppData\Local\Google\Chrome\User Data\Profile 1",
        "windows_roaming": r"C:\Users\someone\AppData\Roaming\Google\Chrome\User Data",
        "windows_forward_slash": "C:/Users/someone/AppData/Local/Google/Chrome/User Data",
        "linux": "/home/someone/.config/google-chrome",
        "linux_chromium": "/home/someone/.config/chromium/Default",
    }

    DEDICATED_PROFILES = {
        "windows_home": r"C:\Users\someone\.sentineldesk\chrome-profile",
        "linux_home": "/home/someone/.sentineldesk/chrome-profile",
        "macos_home": "/Users/someone/.sentineldesk/chrome-profile",
        "temp": "/tmp/sentineldesk-test/chrome-profile",
    }

    def _paths(self, profile: str) -> Paths:
        home = Path("sentineldesk-test-home")
        return Paths(
            home=home,
            config=home / "config.toml",
            database=home / "sentineldesk.sqlite3",
            artifacts=home / "artifacts",
            demo=home / "demo",
            chrome_profile=Path(profile),
        )

    def test_default_profiles_are_detected_on_every_platform(self) -> None:
        for label, profile in self.DEFAULT_PROFILES.items():
            with self.subTest(profile=label):
                self.assertTrue(looks_like_default_profile(Path(profile)), profile)

    def test_default_profiles_are_refused_on_every_platform(self) -> None:
        for label, profile in self.DEFAULT_PROFILES.items():
            with self.subTest(profile=label):
                with self.assertRaisesRegex(ValueError, "default Chrome profile"):
                    launch(self._paths(profile))

    def test_dedicated_lifeagent_profiles_are_not_blocked(self) -> None:
        for label, profile in self.DEDICATED_PROFILES.items():
            with self.subTest(profile=label):
                self.assertFalse(looks_like_default_profile(Path(profile)), profile)

    def test_dedicated_profile_launches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(tmp)
            self.assertFalse(looks_like_default_profile(paths.chrome_profile))
            with patch("sentineldesk.chrome.subprocess.Popen", return_value=object()):
                self.assertIsNotNone(launch(paths))


if __name__ == "__main__":
    unittest.main()
