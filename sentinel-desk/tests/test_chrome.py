from __future__ import annotations

import tempfile
import unittest
import subprocess
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
        self.assertTrue(kwargs["start_new_session"])

    def test_launch_refuses_default_chrome_profile(self) -> None:
        paths = Paths(
            home=Path("/tmp/sentineldesk"),
            config=Path("/tmp/sentineldesk/config.toml"),
            database=Path("/tmp/sentineldesk/sentineldesk.sqlite3"),
            artifacts=Path("/tmp/sentineldesk/artifacts"),
            demo=Path("/tmp/sentineldesk/demo"),
            chrome_profile=Path("~/Library/Application Support/Google/Chrome/Profile 1").expanduser(),
        )
        self.assertTrue(looks_like_default_profile(paths.chrome_profile))
        with self.assertRaisesRegex(ValueError, "default Chrome profile"):
            launch(paths)


if __name__ == "__main__":
    unittest.main()
