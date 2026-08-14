"""Local filesystem paths must not survive redaction — on any platform.

Redaction used to understand POSIX paths only, so a Windows machine leaked its
drive letters, user name, and repository location into every shared artifact.
This file pins the full set of shapes across all three artifact formats the
share package contains (structured JSON, the HTML report, and the ZIP), and
checks the privacy audit actually *detects* an unredacted one rather than
reporting clean.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

from sentineldesk.cli import main
from sentineldesk.redact import redact
from sentineldesk.reports import evidence_report_html, redact_data, write_evidence_package

REDACTED = "[REDACTED_PATH]"

# Every shape the acceptance criteria call out, plus the JSON-escaped spellings
# that only appear once a payload has been serialized.
LOCAL_PATHS = {
    "windows_drive": r"C:\Users\alexdoe\AppData\Local\Temp\evidence.json",
    "windows_forward_slash": "C:/Users/alexdoe/AppData/Local/Temp/evidence.json",
    "windows_other_drive": r"D:\CodingProject\LifeAgent\sentinel-desk",
    "windows_unc": r"\\fileserver\share\team\evidence.json",
    "windows_json_escaped": r"C:\\Users\\alexdoe\\AppData\\Local\\Temp",
    "windows_unc_json_escaped": r"\\\\fileserver\\share\\team",
    "windows_bare_drive_root": "E:" + chr(92),
    # Spaces are the case that regressed: matching used to stop at the first one
    # and leave the rest of the path in the artifact.
    "windows_spaced_user": r"C:\Users\Jane Doe\AppData\Local\Temp\secret.json",
    "windows_spaced_program_files": r"C:\Program Files\My App\tool.exe",
    "windows_spaced_other_drive": r"D:\Review With Spaces Package\artifacts\integrations\run.share.zip",
    "windows_spaced_trailing_dir": r"C:\Users\Jane Doe\My Documents",
    "windows_spaced_forward_slash": "C:/Users/Jane Doe/AppData/Local/Temp/secret.json",
    "windows_spaced_json_escaped": r"C:\\Users\\Jane Doe\\AppData\\Local",
    "windows_unc_spaced": r"\\file server\team share\Jane Doe\evidence.json",
    "posix_user_home": "/Users/alexdoe/Documents/evidence.pdf",
    "posix_spaced_user_home": "/Users/Jane Doe/Documents/my report.pdf",
    "linux_user_home": "/home/alexdoe/work/evidence.pdf",
    "linux_spaced_user_home": "/home/jane doe/work/my report.pdf",
    "posix_tmp": "/tmp/pytest-of-alexdoe/pytest-0/evidence.pdf",
    "posix_var": "/var/folders/qx/T/sentineldesk/evidence.pdf",
}

# Paths embedded in a longer string: no fragment of the path may survive, and the
# surrounding prose must.
EMBEDDED_CASES = [
    (
        r"evidence written to C:\Users\Jane Doe\AppData\Local\Temp\secret.json for review",
        "evidence written to [REDACTED_PATH] for review",
    ),
    (
        r"the tool at C:\Program Files\My App\tool.exe failed",
        "the tool at [REDACTED_PATH] failed",
    ),
    (
        r'quoted "C:\Program Files\My App\tool.exe" here',
        'quoted "[REDACTED_PATH]" here',
    ),
    (
        r"see \\file server\team share\Jane Doe\evidence.json please",
        "see [REDACTED_PATH] please",
    ),
    (
        "artifact at /Users/Jane Doe/Documents/evidence.pdf here",
        "artifact at [REDACTED_PATH] here",
    ),
    (
        r"+ C:\Program Files\My App\python.exe -B -m sentineldesk --home C:\Users\Jane Doe\.demo privacy audit",
        "+ [REDACTED_PATH] -B -m sentineldesk --home [REDACTED_PATH] privacy audit",
    ),
]

# Fragments that must survive: over-redaction would make artifacts useless.
KEEPS = [
    "fixtures/ui/sample_emails.json",
    "sentineldesk daily run --email-json fixtures/ui/sample_emails.json",
    "env:SENTINEL_GOOGLE_TOKEN_JSON:***",
    "The meeting is at 12:30 and section C: overview follows.",
    "docs/UI_CONTRACT.md",
]


class RedactWindowsPathTests(unittest.TestCase):
    def test_a_whole_value_that_is_a_path_becomes_exactly_the_marker(self) -> None:
        for label, path in LOCAL_PATHS.items():
            with self.subTest(shape=label):
                self.assertEqual(redact(path), REDACTED)

    def test_every_local_path_shape_is_replaced_with_one_marker(self) -> None:
        for label, path in LOCAL_PATHS.items():
            with self.subTest(shape=label):
                redacted = redact(f"evidence written to {path} for review")
                self.assertNotIn(path, redacted)
                self.assertIn(REDACTED, redacted)

    def test_no_path_fragment_survives_when_a_path_is_embedded_in_text(self) -> None:
        """The bug this pins: matching used to stop at the first space."""
        for text, expected in EMBEDDED_CASES:
            with self.subTest(text=text):
                self.assertEqual(redact(text), expected)

    def test_spaced_paths_leave_no_recognisable_remnant(self) -> None:
        for label, path in LOCAL_PATHS.items():
            if " " not in path:
                continue
            with self.subTest(shape=label):
                redacted = redact(f"evidence written to {path} for review")
                # Every component of the path must be gone, not just the first.
                for component in re.split(r"[\\/]+", path):
                    component = component.strip()
                    if not component or component.endswith(":"):
                        continue
                    self.assertNotIn(component, redacted, f"{component!r} survived in {redacted!r}")

    def test_relative_paths_and_prose_are_untouched(self) -> None:
        for keep in KEEPS:
            with self.subTest(keep=keep):
                self.assertEqual(redact(keep), keep)

    def test_existing_redaction_capabilities_do_not_regress(self) -> None:
        text = (
            "Contact student@example.edu or 415-555-0134, see https://portal.example.com/case/9,"
            " ssn 123-45-6789, file /Users/alexdoe/report.pdf"
        )
        redacted = redact(text)
        self.assertIn("[REDACTED_EMAIL]", redacted)
        self.assertIn("[REDACTED_PHONE]", redacted)
        self.assertIn("[REDACTED_URL]", redacted)
        self.assertIn("[REDACTED_ID]", redacted)
        self.assertIn(REDACTED, redacted)
        for raw in ("student@example.edu", "415-555-0134", "portal.example.com", "123-45-6789"):
            self.assertNotIn(raw, redacted)


def _evidence_with_local_paths() -> dict:
    return {
        "target_name": "case",
        "target_kind": "lease",
        "captured_at": "2026-08-14T12:00:00Z",
        "alert": {"level": "info", "reason": f"Captured from {LOCAL_PATHS['windows_drive']}"},
        "status": {"value": "current", "evidence": LOCAL_PATHS["windows_forward_slash"]},
        "health": {"state": "ok", "reasons": [LOCAL_PATHS["windows_unc"]]},
        "home": LOCAL_PATHS["windows_other_drive"],
        "artifact_paths": [LOCAL_PATHS["posix_user_home"], LOCAL_PATHS["posix_tmp"]],
        "nested": {"deep": {"path": LOCAL_PATHS["linux_user_home"]}},
        "diff_preview": [f"- old {LOCAL_PATHS['windows_drive']}", "+ new value"],
        "account_id": "student.private@example.com",
        "cursor": "history-secret-123",
        "access_token": "ya29.raw-token-value",
    }


class RedactedArtifactTests(unittest.TestCase):
    """Structured JSON, the HTML report, and the ZIP must all come out clean."""

    def setUp(self) -> None:
        self.evidence = _evidence_with_local_paths()

    def test_structured_json_has_no_raw_paths(self) -> None:
        serialized = json.dumps(redact_data(self.evidence), ensure_ascii=False)
        for label, path in LOCAL_PATHS.items():
            if label.endswith("json_escaped") or label == "windows_bare_drive_root":
                continue  # not present in this payload; covered by the regex tests
            with self.subTest(shape=label):
                self.assertNotIn(path, serialized)
                # The JSON-escaped spelling must be gone too.
                self.assertNotIn(path.replace("\\", "\\\\"), serialized)
        self.assertIn(REDACTED, serialized)

    def test_html_report_has_no_raw_paths(self) -> None:
        html = evidence_report_html(self.evidence)
        for path in (LOCAL_PATHS["windows_drive"], LOCAL_PATHS["windows_unc"], LOCAL_PATHS["posix_user_home"]):
            self.assertNotIn(path, html)
        self.assertIn(REDACTED, html)

    def test_share_zip_has_no_raw_paths_usernames_or_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "windows.share.zip"
            write_evidence_package(package_path, self.evidence)
            with zipfile.ZipFile(package_path) as archive:
                combined = "\n".join(
                    archive.read(name).decode("utf-8") for name in sorted(archive.namelist())
                )

        for label, path in LOCAL_PATHS.items():
            if label.endswith("json_escaped") or label == "windows_bare_drive_root":
                continue
            with self.subTest(shape=label):
                self.assertNotIn(path, combined)
                self.assertNotIn(path.replace("\\", "\\\\"), combined)
        for leak in ("alexdoe", "CodingProject", "fileserver", "ya29.raw-token-value", "history-secret-123"):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, combined)
        self.assertIn(REDACTED, combined)


class PrivacyAuditDetectsWindowsPathsTests(unittest.TestCase):
    def _audit(self, tmp: str) -> dict:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main(["privacy", "audit", "--path", tmp])
        return json.loads(output.getvalue())

    def test_audit_flags_an_injected_unredacted_windows_path(self) -> None:
        """Injecting a raw Windows path must be *found*, not quietly passed."""
        for label in ("windows_drive", "windows_forward_slash", "windows_other_drive", "windows_unc"):
            with self.subTest(shape=label), tempfile.TemporaryDirectory() as tmp:
                leaky = Path(tmp) / "leaky.redacted.json"
                leaky.write_text(json.dumps({"home": LOCAL_PATHS[label]}), encoding="utf-8")

                payload = self._audit(tmp)
                self.assertEqual(payload["status"], "leaks_found", payload)
                self.assertIn("local_path", {issue["kind"] for issue in payload["issues"]})
                # The audit report itself must not echo the raw path back.
                self.assertNotIn(LOCAL_PATHS[label], json.dumps(payload))

    def test_audit_flags_a_windows_path_inside_a_share_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "leaky.share.zip"
            with zipfile.ZipFile(package_path, "w") as archive:
                archive.writestr("verification.redacted.json", json.dumps({"home": LOCAL_PATHS["windows_drive"]}))

            payload = self._audit(tmp)
            self.assertEqual(payload["status"], "leaks_found")
            self.assertIn("local_path", {issue["kind"] for issue in payload["issues"]})

    def test_audit_returns_clean_once_the_same_payload_is_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clean = Path(tmp) / "clean.redacted.json"
            clean.write_text(
                json.dumps(redact_data({"home": LOCAL_PATHS["windows_drive"], "unc": LOCAL_PATHS["windows_unc"]})),
                encoding="utf-8",
            )

            payload = self._audit(tmp)
            self.assertEqual(payload["status"], "clean", payload)
            self.assertEqual(payload["issue_count"], 0)


class RealHomePathIsRedactedTests(unittest.TestCase):
    HOME_NAMES = {
        "plain": "PlainAardvarkHome",
        # The reported failure: a home whose name contains spaces leaked the part
        # of the path after the first space into the shared package. Distinctive
        # nonsense words, so a hit is a real leak and not an English word that the
        # package text happens to contain.
        "with_spaces": "Zephyr Quokka Vault",
    }
    # Only the leaf name is searched word by word. The ancestors are whatever the
    # machine's temp root happens to be, and their components are not always
    # distinctive enough to search for: GitHub's Windows runners use D:\a\_temp,
    # so one component is the single letter "a", which occurs in ordinary prose.
    # The full-path assertions below are what actually catch an ancestor leak.

    def _package(self, home: Path) -> tuple[str, Path]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--home", str(home), "integrations", "check", "--suite", "langgraph", "--package"])
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        with zipfile.ZipFile(Path(payload["package_path"])) as archive:
            combined = "\n".join(archive.read(name).decode("utf-8") for name in sorted(archive.namelist()))
        return combined, Path(payload["package_path"])

    def test_integration_package_never_contains_the_real_home_path(self) -> None:
        """End-to-end: the machine's actual temp/home path must not reach the ZIP."""
        for label, name in self.HOME_NAMES.items():
            with self.subTest(home=label), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / name
                combined, _ = self._package(home)

                self.assertNotIn(str(home), combined)
                self.assertNotIn(str(Path(tmp)), combined)
                self.assertNotIn(home.as_posix(), combined)
                self.assertNotIn(Path(tmp).as_posix(), combined)
                if len(Path.home().name) >= 5:
                    self.assertNotIn(Path.home().name, combined)
                # Every word of the home directory name must be gone, not just the
                # first — that is the spaced-path regression.
                for word in name.split():
                    self.assertNotIn(word, combined, f"{word!r} survived")

    def test_privacy_audit_is_clean_for_a_home_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / self.HOME_NAMES["with_spaces"]
            self._package(home)

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--home", str(home), "privacy", "audit", "--path", str(home), "--require-clean"])
            payload = json.loads(output.getvalue())

        self.assertEqual(payload["status"], "clean", payload)
        self.assertEqual(code, 0)
        self.assertGreater(payload["scanned_count"], 0, "the audit must actually have scanned something")


class PreflightOutputPathTests(unittest.TestCase):
    def test_preflight_transcript_redacts_a_home_with_spaces(self) -> None:
        from dataclasses import replace

        from sentineldesk.integrations.live_verification import PreflightConfig, run_preflight

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "Zephyr Quokka Vault"
            config = replace(PreflightConfig.from_environment(), home=home, dry_run=True)
            stream = io.StringIO()
            code = run_preflight(config, stream=stream, runner=lambda argv: 0)
            transcript = stream.getvalue()

        self.assertEqual(code, 0)
        self.assertNotIn(str(home), transcript)
        for word in ("Zephyr", "Quokka", "Vault"):
            self.assertNotIn(word, transcript, f"{word!r} survived in the preflight transcript")
        self.assertIn(REDACTED, transcript)


if __name__ == "__main__":
    unittest.main()
