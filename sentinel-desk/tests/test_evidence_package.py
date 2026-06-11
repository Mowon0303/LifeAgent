from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from sentineldesk import db
from sentineldesk.cli import main
from sentineldesk.config import ensure_dirs, file_url, get_paths, project_root
from sentineldesk.extract import utc_now
from sentineldesk.monitor import run_target
from sentineldesk.reports import write_evidence_package


FIXTURES = project_root() / "fixtures" / "portals"


class EvidencePackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = get_paths(self.tmp.name)
        ensure_dirs(self.paths)
        db.init_db(self.paths)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def make_run(self) -> dict:
        db.upsert_target(
            self.paths,
            name="case",
            url=file_url(FIXTURES / "opt_action_required.html") + "?email=a@example.com",
            kind="opt",
            high_stakes=True,
            created_at=utc_now(),
        )
        target = db.get_target(self.paths, name="case")
        assert target is not None
        return run_target(self.paths, target)

    def test_cli_creates_redacted_share_package(self) -> None:
        run = self.make_run()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--home", str(self.paths.home), "evidence", run["run_id"], "--package"])
        self.assertEqual(code, 0)
        package_path = Path(output.getvalue().strip())
        self.assertTrue(package_path.exists())
        self.assertEqual(package_path.suffix, ".zip")

        with zipfile.ZipFile(package_path) as archive:
            names = set(archive.namelist())
            self.assertEqual(names, {"README.md", "manifest.json", "evidence.redacted.json", "report.html"})
            combined = "\n".join(archive.read(name).decode("utf-8") for name in sorted(names))

        self.assertIn("sentineldesk-redacted-evidence-v1", combined)
        self.assertIn("[REDACTED_URL]", combined)
        self.assertNotIn("file://", combined)
        self.assertNotIn("a@example.com", combined)
        self.assertNotIn(str(self.paths.home), combined)

    def test_share_package_redacts_email_headers_attachments_invitees_and_connector_metadata(self) -> None:
        package_path = Path(self.tmp.name) / "share.zip"
        write_evidence_package(
            package_path,
            {
                "target_name": "privacy-case",
                "target_kind": "lease",
                "captured_at": "2026-06-11T12:00:00Z",
                "alert": {"level": "info", "reason": "Synthetic evidence"},
                "status": {"value": "draft"},
                "health": {"state": "ok", "reasons": []},
                "email_headers": {
                    "from": "student@example.com",
                    "to": "office@school.edu",
                    "authorization": "Bearer ya29.hidden-token",
                },
                "attachment_names": ["Zuge_Li_I765_A123456789.pdf", "lease-ledger.pdf"],
                "calendar_event": {
                    "invitees": [{"email": "landlord@example.com", "display_name": "Private Landlord"}],
                    "organizer": "Zuge Li <zugeli@example.com>",
                },
                "connector_metadata": {
                    "account_id": "zugeli@gmail.com",
                    "cursor": "history-987654321",
                    "sync_token": "sync-token-private",
                    "access_token": "ya29.private",
                },
            },
        )

        with zipfile.ZipFile(package_path) as archive:
            payload = json.loads(archive.read("evidence.redacted.json").decode("utf-8"))
            combined = "\n".join(archive.read(name).decode("utf-8") for name in sorted(archive.namelist()))

        self.assertEqual(payload["email_headers"]["from"], "[REDACTED_EMAIL]")
        self.assertEqual(payload["email_headers"]["authorization"], "[REDACTED_SECRET]")
        self.assertEqual(payload["attachment_names"], ["[REDACTED_ATTACHMENT]", "[REDACTED_ATTACHMENT]"])
        self.assertEqual(payload["calendar_event"]["invitees"], ["[REDACTED_INVITEE]"])
        self.assertEqual(payload["connector_metadata"]["cursor"], "[REDACTED_CONNECTOR_METADATA]")
        for raw_value in [
            "student@example.com",
            "office@school.edu",
            "ya29",
            "Zuge_Li_I765",
            "lease-ledger.pdf",
            "Private Landlord",
            "landlord@example.com",
            "history-987654321",
            "sync-token-private",
            "zugeli@gmail.com",
        ]:
            self.assertNotIn(raw_value, combined)

    def test_package_command_fails_for_missing_run(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            code = main(["--home", str(self.paths.home), "evidence", "missing", "--package"])
        self.assertEqual(code, 1)
        self.assertIn("No run found", output.getvalue())


if __name__ == "__main__":
    unittest.main()
