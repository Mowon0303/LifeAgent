from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from sentineldesk.cli import main
from sentineldesk.reports import write_evidence_package


class PrivacyAuditTests(unittest.TestCase):
    def test_privacy_audit_passes_clean_redacted_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "clean.share.zip"
            write_evidence_package(
                package_path,
                {
                    "target_name": "case",
                    "target_kind": "lease",
                    "captured_at": "2026-06-11T12:00:00Z",
                    "alert": {"level": "info", "reason": "Synthetic"},
                    "status": {"value": "current"},
                    "health": {"state": "ok", "reasons": []},
                    "email_headers": {"from": "student@example.com"},
                    "local_path": "/Users/example/private/file.pdf",
                    "access_token": "ya29.hidden",
                },
            )

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["privacy", "audit", "--path", tmp, "--require-clean"])

            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "clean")
            self.assertEqual(payload["issue_count"], 0)
            self.assertEqual(payload["scanned_count"], 1)

    def test_privacy_audit_fails_without_echoing_raw_leaks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "leaky.share.zip"
            with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    "verification.redacted.json",
                    json.dumps(
                        {
                            "email": "student@example.edu",
                            "path": "/Users/zuge/private/report.pdf",
                            "access_token": "raw-secret-token",
                        }
                    ),
                )

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["privacy", "audit", "--path", tmp, "--require-clean"])

            raw = output.getvalue()
            self.assertEqual(code, 1)
            self.assertNotIn("student@example.edu", raw)
            self.assertNotIn("/Users/zuge/private/report.pdf", raw)
            self.assertNotIn("raw-secret-token", raw)
            payload = json.loads(raw)
            self.assertEqual(payload["status"], "leaks_found")
            kinds = {issue["kind"] for issue in payload["issues"]}
            self.assertIn("email", kinds)
            self.assertIn("local_path", kinds)
            self.assertIn("secret_value", kinds)

    def test_release_audit_passes_clean_project_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sentineldesk").mkdir()
            (root / "sentineldesk" / "module.py").write_text("print('synthetic')\n", encoding="utf-8")
            (root / "fixtures").mkdir()
            (root / "fixtures" / "demo.html").write_text("<p>example.com fixture</p>\n", encoding="utf-8")

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["privacy", "release-audit", "--path", tmp, "--require-clean"])

            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "clean")
            self.assertEqual(payload["issue_count"], 0)
            self.assertGreaterEqual(payload["scanned_files"], 2)

    def test_release_audit_fails_for_runtime_artifacts_without_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "module.cpython-314.pyc").write_bytes(b"bytecode")
            (root / ".demo").mkdir()
            (root / "artifacts").mkdir()
            (root / "private.sqlite3").write_text("sqlite", encoding="utf-8")
            (root / "screen.png").write_bytes(b"png")
            (root / "report.share.zip").write_bytes(b"zip")

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["privacy", "release-audit", "--path", tmp, "--require-clean"])

            raw = output.getvalue()
            self.assertEqual(code, 1)
            self.assertNotIn(tmp, raw)
            payload = json.loads(raw)
            self.assertEqual(payload["status"], "artifacts_found")
            artifacts = {issue["artifact"] for issue in payload["issues"]}
            self.assertIn("__pycache__", artifacts)
            self.assertIn(".demo", artifacts)
            self.assertIn("artifacts", artifacts)
            self.assertIn("private.sqlite3", artifacts)
            self.assertIn("screen.png", artifacts)
            self.assertIn("report.share.zip", artifacts)
            kinds = {issue["kind"] for issue in payload["issues"]}
            self.assertIn("runtime_directory", kinds)
            self.assertIn("local_database", kinds)
            self.assertIn("image_or_screenshot_artifact", kinds)
            self.assertIn("share_package", kinds)

    def test_release_package_excludes_runtime_artifacts_and_reaudits_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            (root / "sentineldesk").mkdir()
            (root / "sentineldesk" / "module.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "module.cpython-314.pyc").write_bytes(b"bytecode")
            (root / ".agent-venv").mkdir()
            (root / ".agent-venv" / "pyvenv.cfg").write_text("home = hidden\n", encoding="utf-8")
            (root / ".demo").mkdir()
            (root / ".demo" / "sentineldesk.sqlite3").write_text("sqlite", encoding="utf-8")
            (root / "sentineldesk.egg-info").mkdir()
            (root / "sentineldesk.egg-info" / "PKG-INFO").write_text("metadata", encoding="utf-8")
            (root / "screen.png").write_bytes(b"png")
            output_zip = Path(tmp) / "release.zip"

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["privacy", "release-package", "--source", str(root), "--output", str(output_zip)])

            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "written")
            self.assertTrue(output_zip.exists())
            self.assertGreaterEqual(payload["excluded_count"], 5)
            with zipfile.ZipFile(output_zip) as archive:
                names = set(archive.namelist())
            self.assertEqual(names, {"sentineldesk/module.py"})

            extracted = Path(tmp) / "extracted"
            with zipfile.ZipFile(output_zip) as archive:
                archive.extractall(extracted)
            audit_output = io.StringIO()
            with contextlib.redirect_stdout(audit_output):
                code = main(["privacy", "release-audit", "--path", str(extracted), "--require-clean"])

            self.assertEqual(code, 0)
            self.assertEqual(json.loads(audit_output.getvalue())["status"], "clean")


if __name__ == "__main__":
    unittest.main()
