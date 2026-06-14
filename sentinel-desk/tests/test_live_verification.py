from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from sentineldesk import db
from sentineldesk.cli import main
from sentineldesk.config import ensure_config, ensure_dirs, get_paths
from sentineldesk.email.connectors import EmailSyncRequest, GmailApiEmailConnector
from sentineldesk.email.ingest import sync_connector
from sentineldesk.integrations.google_workspace import GMAIL_READONLY_SCOPE
from sentineldesk.integrations.live_verification import build_completion_audit, run_verification
from sentineldesk.server import Handler


class FakeSocket:
    def __init__(self, request: bytes) -> None:
        self.request = io.BytesIO(request)
        self.response = io.BytesIO()

    def makefile(self, mode: str, *args: object, **kwargs: object) -> io.BytesIO:
        if "r" in mode:
            return self.request
        return self.response

    def sendall(self, data: bytes) -> None:
        self.response.write(data)


def parse_response(raw: bytes) -> tuple[int, dict[str, str], bytes]:
    header_bytes, body = raw.split(b"\r\n\r\n", 1)
    header_lines = header_bytes.decode("iso-8859-1").split("\r\n")
    status = int(header_lines[0].split(" ")[1])
    headers: dict[str, str] = {}
    for line in header_lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.lower()] = value.strip()
    return status, headers, body


class _PackageShapeGmailClient:
    account_id = "student.private@example.com"
    scopes = (GMAIL_READONLY_SCOPE,)

    def search_messages(self, query: str, since: str, limit: int) -> dict[str, object]:
        return {
            "cursor": "history-shape-123",
            "raw_count": 1,
            "messages": [
                {
                    "id": "gmail-shape-1",
                    "thread_id": "thread-shape-1",
                    "from": "school.private@example.com",
                    "subject": "Package shape deadline",
                    "date": "2026-06-11",
                    "body": "Submit the housing form by July 15, 2026.",
                }
            ],
        }


class LiveVerificationTests(unittest.TestCase):
    def test_run_verification_persists_redacted_report_without_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(Path(tmp) / "home")
            ensure_dirs(paths)
            old = os.environ.get("SENTINEL_TEST_GOOGLE_TOKEN")
            os.environ["SENTINEL_TEST_GOOGLE_TOKEN"] = '{"access_token":"super-secret-token"}'
            try:
                report = run_verification(
                    paths,
                    suite="gmail",
                    google_token_env="SENTINEL_TEST_GOOGLE_TOKEN",
                    google_credentials_env="SENTINEL_TEST_MISSING_CREDS",
                    persist=True,
                    created_at="2026-06-10T12:00:00Z",
                )
            finally:
                if old is None:
                    os.environ.pop("SENTINEL_TEST_GOOGLE_TOKEN", None)
                else:
                    os.environ["SENTINEL_TEST_GOOGLE_TOKEN"] = old

            self.assertEqual(report.suite, "gmail")
            self.assertIn(report.status, {"partial", "missing"})
            self.assertTrue(Path(report.artifact_path).exists())
            artifact = Path(report.artifact_path).read_text(encoding="utf-8")
            self.assertIn("env:SENTINEL_TEST_GOOGLE_TOKEN:***", artifact)
            self.assertNotIn("super-secret-token", artifact)
            stored = db.list_integration_verifications(paths)
            self.assertEqual(stored[0]["verification_id"], report.verification_id)
            self.assertEqual(db.list_audit_events(paths)[0]["action"], "integration.verify")

    def test_cli_integrations_check_and_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--home", str(home), "integrations", "check", "--suite", "langgraph"])
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["suite"], "langgraph")
            self.assertTrue(payload["checks"])
            self.assertTrue(Path(payload["artifact_path"]).exists())

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--home", str(home), "integrations", "reports"])
            self.assertEqual(code, 0)
            reports = json.loads(output.getvalue())
            self.assertEqual(reports[0]["verification_id"], payload["verification_id"])

    def test_google_token_scope_checks_do_not_expose_token_values(self) -> None:
        token_env = "SENTINEL_TEST_SCOPED_GOOGLE_TOKEN"
        old = os.environ.get(token_env)
        os.environ[token_env] = json.dumps(
            {
                "token": "scoped-secret-token",
                "refresh_token": "scoped-refresh-token",
                "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
            }
        )
        try:
            with tempfile.TemporaryDirectory() as tmp:
                report = run_verification(
                    get_paths(Path(tmp) / "home"),
                    suite="all",
                    google_token_env=token_env,
                    persist=False,
                )
        finally:
            if old is None:
                os.environ.pop(token_env, None)
            else:
                os.environ[token_env] = old

        checks = {check.name: check for check in report.checks}
        self.assertEqual(checks["gmail.token_scope"].status, "ready")
        self.assertEqual(checks["google_calendar.token_scope"].status, "missing")
        self.assertEqual(
            checks["google_calendar.token_scope"].metadata["missing_scopes"],
            ["https://www.googleapis.com/auth/calendar.events"],
        )
        raw = json.dumps(report.to_dict())
        self.assertNotIn("scoped-secret-token", raw)
        self.assertNotIn("scoped-refresh-token", raw)

    def test_google_secret_format_checks_reject_malformed_values_without_leaking(self) -> None:
        credentials_env = "SENTINEL_TEST_BAD_GOOGLE_CREDS"
        token_env = "SENTINEL_TEST_BAD_GOOGLE_TOKEN"
        old_credentials = os.environ.get(credentials_env)
        old_token = os.environ.get(token_env)
        os.environ[credentials_env] = "not-json-client-secret"
        os.environ[token_env] = "not-json-token-secret"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                report = run_verification(
                    get_paths(Path(tmp) / "home"),
                    suite="all",
                    google_credentials_env=credentials_env,
                    google_token_env=token_env,
                    persist=False,
                )
        finally:
            if old_credentials is None:
                os.environ.pop(credentials_env, None)
            else:
                os.environ[credentials_env] = old_credentials
            if old_token is None:
                os.environ.pop(token_env, None)
            else:
                os.environ[token_env] = old_token

        checks = {check.name: check for check in report.checks}
        self.assertEqual(checks["gmail.credentials_format"].status, "invalid")
        self.assertEqual(checks["gmail.token_format"].status, "invalid")
        self.assertEqual(checks["google_calendar.credentials_format"].status, "invalid")
        self.assertEqual(checks["google_calendar.token_format"].status, "invalid")
        self.assertFalse(checks["gmail.credentials_format"].metadata["json_parseable"])
        self.assertFalse(checks["gmail.token_format"].metadata["json_parseable"])
        raw = json.dumps(report.to_dict())
        self.assertNotIn("not-json-client-secret", raw)
        self.assertNotIn("not-json-token-secret", raw)

    def test_google_secret_format_checks_accept_expected_oauth_shapes(self) -> None:
        credentials_env = "SENTINEL_TEST_GOOGLE_CREDS_FORMAT"
        token_env = "SENTINEL_TEST_GOOGLE_TOKEN_FORMAT"
        old_credentials = os.environ.get(credentials_env)
        old_token = os.environ.get(token_env)
        os.environ[credentials_env] = json.dumps(
            {
                "installed": {
                    "client_id": "format-client-id",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
        )
        os.environ[token_env] = json.dumps(
            {
                "token": "format-access-token",
                "refresh_token": "format-refresh-token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "format-client-id",
                "client_secret": "format-client-secret",
                "scopes": [
                    "https://www.googleapis.com/auth/gmail.readonly",
                    "https://www.googleapis.com/auth/calendar.events",
                ],
            }
        )
        try:
            with tempfile.TemporaryDirectory() as tmp:
                report = run_verification(
                    get_paths(Path(tmp) / "home"),
                    suite="all",
                    google_credentials_env=credentials_env,
                    google_token_env=token_env,
                    persist=False,
                )
        finally:
            if old_credentials is None:
                os.environ.pop(credentials_env, None)
            else:
                os.environ[credentials_env] = old_credentials
            if old_token is None:
                os.environ.pop(token_env, None)
            else:
                os.environ[token_env] = old_token

        checks = {check.name: check for check in report.checks}
        self.assertEqual(checks["gmail.credentials_format"].status, "ready")
        self.assertEqual(checks["gmail.token_format"].status, "ready")
        self.assertEqual(checks["gmail.token_scope"].status, "ready")
        self.assertEqual(checks["google_calendar.credentials_format"].status, "ready")
        self.assertEqual(checks["google_calendar.token_format"].status, "ready")
        self.assertEqual(checks["google_calendar.token_scope"].status, "ready")
        raw = json.dumps(report.to_dict())
        self.assertNotIn("format-access-token", raw)
        self.assertNotIn("format-refresh-token", raw)
        self.assertNotIn("format-client-secret", raw)

    def test_apple_calendar_secret_format_checks_reject_malformed_values_without_leaking(self) -> None:
        user_env = "SENTINEL_TEST_BAD_APPLE_USER"
        password_env = "SENTINEL_TEST_BAD_APPLE_PASSWORD"
        old_user = os.environ.get(user_env)
        old_password = os.environ.get(password_env)
        os.environ[user_env] = "bad apple user"
        os.environ[password_env] = "short"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                report = run_verification(
                    get_paths(Path(tmp) / "home"),
                    suite="calendar",
                    apple_user_env=user_env,
                    apple_password_env=password_env,
                    persist=False,
                )
        finally:
            if old_user is None:
                os.environ.pop(user_env, None)
            else:
                os.environ[user_env] = old_user
            if old_password is None:
                os.environ.pop(password_env, None)
            else:
                os.environ[password_env] = old_password

        checks = {check.name: check for check in report.checks}
        self.assertEqual(checks["apple_calendar.username_format"].status, "invalid")
        self.assertEqual(checks["apple_calendar.app_password_format"].status, "invalid")
        self.assertTrue(checks["apple_calendar.username_format"].metadata["contains_whitespace"])
        self.assertEqual(checks["apple_calendar.app_password_format"].metadata["normalized_length"], 5)
        raw = json.dumps(report.to_dict())
        self.assertNotIn("bad apple user", raw)
        self.assertNotIn("short", raw)

    def test_apple_calendar_secret_format_checks_accept_plausible_values_without_leaking(self) -> None:
        user_env = "SENTINEL_TEST_APPLE_USER_FORMAT"
        password_env = "SENTINEL_TEST_APPLE_PASSWORD_FORMAT"
        old_user = os.environ.get(user_env)
        old_password = os.environ.get(password_env)
        os.environ[user_env] = "appleid@example.com"
        os.environ[password_env] = "abcd-efgh-ijkl-mnop"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                report = run_verification(
                    get_paths(Path(tmp) / "home"),
                    suite="calendar",
                    apple_user_env=user_env,
                    apple_password_env=password_env,
                    persist=False,
                )
        finally:
            if old_user is None:
                os.environ.pop(user_env, None)
            else:
                os.environ[user_env] = old_user
            if old_password is None:
                os.environ.pop(password_env, None)
            else:
                os.environ[password_env] = old_password

        checks = {check.name: check for check in report.checks}
        self.assertEqual(checks["apple_calendar.username_format"].status, "ready")
        self.assertEqual(checks["apple_calendar.app_password_format"].status, "ready")
        self.assertTrue(checks["apple_calendar.app_password_format"].metadata["dashed_format"])
        raw = json.dumps(report.to_dict())
        self.assertNotIn("appleid@example.com", raw)
        self.assertNotIn("abcd-efgh-ijkl-mnop", raw)

    def test_run_verification_allocates_unique_ids_with_same_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(Path(tmp) / "home")
            first = run_verification(paths, suite="langgraph", persist=True, created_at="2026-06-10T12:00:00Z")
            second = run_verification(paths, suite="langgraph", persist=True, created_at="2026-06-10T12:00:00Z")

            self.assertNotEqual(first.verification_id, second.verification_id)
            self.assertTrue(second.verification_id.endswith("-2"))
            self.assertTrue(Path(first.artifact_path).exists())
            self.assertTrue(Path(second.artifact_path).exists())
            stored_ids = [item["verification_id"] for item in db.list_integration_verifications(paths, limit=10)]
            self.assertIn(first.verification_id, stored_ids)
            self.assertIn(second.verification_id, stored_ids)

    def test_cli_integrations_package_writes_redacted_share_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            secret_name = "SENTINEL_TEST_PACKAGE_TOKEN"
            old = os.environ.get(secret_name)
            os.environ[secret_name] = '{"access_token":"package-secret-token"}'
            try:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = main(
                        [
                            "--home",
                            str(home),
                            "integrations",
                            "check",
                            "--suite",
                            "gmail",
                            "--google-token-env",
                            secret_name,
                        ]
                    )
                self.assertEqual(code, 0)
                verification = json.loads(output.getvalue())

                package_output = io.StringIO()
                with contextlib.redirect_stdout(package_output):
                    code = main(["--home", str(home), "integrations", "package", "latest"])
            finally:
                if old is None:
                    os.environ.pop(secret_name, None)
                else:
                    os.environ[secret_name] = old

            self.assertEqual(code, 0)
            package_payload = json.loads(package_output.getvalue())
            self.assertEqual(package_payload["verification_id"], verification["verification_id"])
            package_path = Path(package_payload["package_path"])
            self.assertTrue(package_path.exists())
            with zipfile.ZipFile(package_path) as archive:
                names = set(archive.namelist())
                self.assertEqual(names, {"README.md", "manifest.json", "verification.redacted.json", "report.html"})
                combined = "\n".join(archive.read(name).decode("utf-8") for name in sorted(names))
            self.assertNotIn("package-secret-token", combined)
            self.assertNotIn(str(home), combined)
            self.assertIn("env:SENTINEL_TEST_PACKAGE_TOKEN:***", combined)
            self.assertIn("[REDACTED_PATH]", combined)

    def test_cli_integrations_check_package_writes_package_in_one_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--home", str(home), "integrations", "check", "--suite", "langgraph", "--package"])

            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertIn("package_path", payload)
            package_path = Path(payload["package_path"])
            self.assertTrue(package_path.exists())
            with zipfile.ZipFile(package_path) as archive:
                self.assertIn("verification.redacted.json", archive.namelist())
            stored = db.list_integration_verifications(get_paths(home))
            self.assertEqual(stored[0]["verification_id"], payload["verification_id"])

    def test_gmail_first_readiness_package_shape_after_sync(self) -> None:
        credentials_env = "SENTINEL_TEST_GMAIL_SHAPE_CREDS"
        token_env = "SENTINEL_TEST_GMAIL_SHAPE_TOKEN"
        old_credentials = os.environ.get(credentials_env)
        old_token = os.environ.get(token_env)
        os.environ[credentials_env] = json.dumps(
            {
                "installed": {
                    "client_id": "shape-client-id",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
        )
        os.environ[token_env] = json.dumps(
            {
                "token": "shape-access-token",
                "refresh_token": "shape-refresh-token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "shape-client-id",
                "client_secret": "shape-client-secret",
                "scopes": [GMAIL_READONLY_SCOPE],
            }
        )
        try:
            with tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / "home"
                paths = get_paths(home)
                sync_connector(
                    paths,
                    GmailApiEmailConnector(_PackageShapeGmailClient()),
                    EmailSyncRequest(query="deadline OR due", since="history-0", limit=10),
                    account_id="student.private@example.com",
                    ingested_at="2026-06-11T12:00:00Z",
                )

                output = io.StringIO()
                with patch(
                    "sentineldesk.integrations.live_verification.checks.importlib.util.find_spec",
                    return_value=object(),
                ):
                    with contextlib.redirect_stdout(output):
                        code = main(
                            [
                                "--home",
                                str(home),
                                "integrations",
                                "check",
                                "--suite",
                                "gmail",
                                "--account",
                                "student.private@example.com",
                                "--google-credentials-env",
                                credentials_env,
                                "--google-token-env",
                                token_env,
                                "--require-ready",
                                "--package",
                            ]
                        )

                self.assertEqual(code, 0)
                payload = json.loads(output.getvalue())
                self.assertEqual(payload["suite"], "gmail")
                self.assertEqual(payload["status"], "ready")
                package_path = Path(payload["package_path"])
                self.assertTrue(package_path.exists())
                self.assertEqual(package_path.parent.name, "integrations")

                with zipfile.ZipFile(package_path) as archive:
                    names = set(archive.namelist())
                    self.assertEqual(names, {"README.md", "manifest.json", "verification.redacted.json", "report.html"})
                    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                    verification = json.loads(archive.read("verification.redacted.json").decode("utf-8"))
                    combined = "\n".join(archive.read(name).decode("utf-8") for name in sorted(names))

                self.assertEqual(manifest["package_format"], "sentineldesk-redacted-integration-verification-v1")
                self.assertEqual(manifest["suite"], "gmail")
                self.assertEqual(manifest["status"], "ready")
                self.assertEqual(manifest["check_count"], 10)
                self.assertEqual(
                    manifest["files"],
                    ["README.md", "manifest.json", "verification.redacted.json", "report.html"],
                )
                self.assertEqual(verification["artifact_path"], "[REDACTED_PATH]")
                checks = {check["name"]: check for check in verification["checks"]}
                self.assertEqual(
                    set(checks),
                    {
                        "gmail.credentials",
                        "gmail.credentials_format",
                        "gmail.token",
                        "gmail.token_format",
                        "gmail.token_scope",
                        "gmail.googleapiclient",
                        "gmail.oauth_credentials",
                        "gmail.oauth_flow",
                        "gmail.scope",
                        "gmail.cursor",
                    },
                )
                self.assertTrue(all(check["status"] == "ready" for check in checks.values()))
                self.assertEqual(checks["gmail.cursor"]["metadata"]["account_id"], "[REDACTED_CONNECTOR_METADATA]")
                self.assertEqual(checks["gmail.cursor"]["metadata"]["connector"], "gmail_api")
                self.assertTrue(checks["gmail.cursor"]["metadata"]["has_cursor"])
                self.assertEqual(checks["gmail.credentials"]["metadata"]["redacted"], f"env:{credentials_env}:***")
                self.assertEqual(checks["gmail.token"]["metadata"]["redacted"], f"env:{token_env}:***")
                self.assertIn("Gmail readonly scope is configured.", combined)
                for raw_value in [
                    "shape-access-token",
                    "shape-refresh-token",
                    "shape-client-secret",
                    "shape-client-id",
                    "student.private@example.com",
                    "school.private@example.com",
                    "history-shape-123",
                    str(home),
                ]:
                    self.assertNotIn(raw_value, combined)

                audit_output = io.StringIO()
                with contextlib.redirect_stdout(audit_output):
                    audit_code = main(["--home", str(home), "privacy", "audit", "--require-clean"])
                self.assertEqual(audit_code, 0)
                audit = json.loads(audit_output.getvalue())
                self.assertEqual(audit["status"], "clean")
                self.assertEqual(audit["issue_count"], 0)
        finally:
            if old_credentials is None:
                os.environ.pop(credentials_env, None)
            else:
                os.environ[credentials_env] = old_credentials
            if old_token is None:
                os.environ.pop(token_env, None)
            else:
                os.environ[token_env] = old_token

    def test_cli_integrations_check_package_requires_persistence(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["integrations", "check", "--suite", "langgraph", "--package", "--no-persist"])

        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["error"], "integrations check --package requires persistence; remove --no-persist")

    def test_cli_integrations_completion_audit_requires_final_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            missing_release = Path(tmp) / "missing-release"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(
                    [
                        "--home",
                        str(home),
                        "integrations",
                        "completion-audit",
                        "--account",
                        "sandbox@example.com",
                        "--source-release-path",
                        str(missing_release),
                        "--require-ready",
                    ]
                )

            self.assertEqual(code, 1)
            payload = json.loads(output.getvalue())
            self.assertFalse(payload["ready"])
            requirement_names = [item["name"] for item in payload["missing_requirements"]]
            self.assertIn("current_all_readiness", requirement_names)
            self.assertIn("final_redacted_package", requirement_names)
            self.assertIn("source_release_audit", requirement_names)
            self.assertIn("redacted_output_privacy", [item["name"] for item in payload["requirements"]])
            self.assertTrue(any("integrations check --suite all" in command for command in payload["next_commands"]))
            self.assertTrue(any("privacy release-package" in command for command in payload["next_commands"]))
            self.assertTrue(any("privacy release-audit" in command for command in payload["next_commands"]))
            self.assertIn("does not call external services", payload["privacy"])
            action_plan = {item["id"]: item for item in payload["readiness_action_plan"]}
            self.assertEqual(action_plan["run_gmail_sync"]["status"], "missing")
            self.assertEqual(action_plan["run_gmail_sync"]["side_effect"], "external_read")
            self.assertTrue(action_plan["run_gmail_sync"]["requires_user_approval"])
            self.assertEqual(action_plan["confirm_google_calendar_sync"]["side_effect"], "external_calendar_write")
            self.assertTrue(action_plan["confirm_google_calendar_sync"]["requires_user_approval"])
            self.assertEqual(action_plan["confirm_apple_calendar_sync"]["side_effect"], "external_calendar_write")
            self.assertIn("final_redacted_package", action_plan["write_final_redacted_package"]["missing_checks"])
            self.assertIn("redacted_output_privacy", action_plan["run_final_privacy_audit"]["missing_checks"])
            self.assertIn("source_release_audit", action_plan["run_source_release_audit"]["missing_checks"])
            self.assertNotIn("app-specific-password", json.dumps(payload))

    def test_completion_audit_marks_clean_source_release_audit_ready_without_leaking_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "release"
            package = root / "sentineldesk"
            package.mkdir(parents=True)
            (root / "README.md").write_text("# Clean release\n", encoding="utf-8")
            (package / "__init__.py").write_text("__version__ = '0.0.0'\n", encoding="utf-8")

            audit = build_completion_audit(
                get_paths(Path(tmp) / "home"),
                account_id="sandbox@example.com",
                source_release_path=str(root),
            )

        source_requirement = next(item for item in audit["requirements"] if item["name"] == "source_release_audit")
        self.assertEqual(source_requirement["status"], "ready")
        self.assertEqual(source_requirement["audit_status"], "clean")
        self.assertEqual(source_requirement["issue_count"], 0)
        self.assertEqual(source_requirement["source_release_path"], "[REDACTED_PATH]")
        self.assertNotIn(str(root), json.dumps(audit))

    def test_completion_audit_fails_when_redacted_package_privacy_audit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(Path(tmp) / "home")
            ensure_dirs(paths)
            db.init_db(paths)
            verification_id = "20260611T120000+0000-all"
            report_path = paths.artifacts / "integrations" / f"{verification_id}.json"
            package_path = paths.artifacts / "integrations" / f"{verification_id}.share.zip"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps({"verification_id": verification_id, "suite": "all", "status": "ready"}), encoding="utf-8")
            db.insert_integration_verification(
                paths,
                verification_id=verification_id,
                suite="all",
                status="ready",
                checks=[],
                artifact_path=str(report_path),
                created_at="2026-06-11T12:00:00Z",
            )
            with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    "verification.redacted.json",
                    json.dumps({"email": "student@example.edu", "access_token": "raw-secret-token"}),
                )

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--home", str(paths.home), "integrations", "completion-audit", "--account", "sandbox@example.com", "--require-ready"])

            raw = output.getvalue()
            self.assertEqual(code, 1)
            self.assertNotIn("student@example.edu", raw)
            self.assertNotIn("raw-secret-token", raw)
            payload = json.loads(raw)
            requirement_names = [item["name"] for item in payload["missing_requirements"]]
            self.assertIn("redacted_output_privacy", requirement_names)
            privacy_requirement = next(item for item in payload["requirements"] if item["name"] == "redacted_output_privacy")
            self.assertEqual(privacy_requirement["issue_count"], 2)

    def test_cli_integrations_handoff_writes_human_checklist_without_secret_values(self) -> None:
        old = os.environ.get("SENTINEL_GOOGLE_TOKEN_JSON")
        os.environ["SENTINEL_GOOGLE_TOKEN_JSON"] = '{"access_token":"handoff-secret-token"}'
        try:
            with tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / "home"
                output_path = Path(tmp) / "handoff.md"
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = main(
                        [
                            "--home",
                            str(home),
                            "integrations",
                            "handoff",
                            "--account",
                            "sandbox@example.com",
                            "--output",
                            str(output_path),
                        ]
                    )
                payload = json.loads(output.getvalue())
                checklist = output_path.read_text(encoding="utf-8")
                raw_output = output.getvalue()
        finally:
            if old is None:
                os.environ.pop("SENTINEL_GOOGLE_TOKEN_JSON", None)
            else:
                os.environ["SENTINEL_GOOGLE_TOKEN_JSON"] = old

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "written")
        self.assertFalse(payload["ready"])
        self.assertIn("# LifeAgent Live Verification Handoff", checklist)
        self.assertIn("`external_read`", checklist)
        self.assertIn("`external_calendar_write`", checklist)
        self.assertIn("Requires user approval: `yes`", checklist)
        self.assertIn("`run_source_release_audit`", checklist)
        self.assertIn("privacy release-package", checklist)
        self.assertIn("privacy release-audit", checklist)
        self.assertNotIn("handoff-secret-token", checklist)
        self.assertNotIn("handoff-secret-token", raw_output)

    def test_cli_integrations_handoff_require_ready_fails_when_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(
                    [
                        "--home",
                        str(Path(tmp) / "home"),
                        "integrations",
                        "handoff",
                        "--account",
                        "sandbox@example.com",
                        "--require-ready",
                    ]
                )
        self.assertEqual(code, 1)
        raw = output.getvalue()
        self.assertIn("# LifeAgent Live Verification Handoff", raw)
        self.assertIn("Overall status: `not_ready`", raw)

    def test_cli_integrations_seed_calendar_draft_is_local_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(
                    [
                        "--home",
                        str(home),
                        "integrations",
                        "seed-calendar-draft",
                        "--date",
                        "2026-07-20",
                        "--source-id",
                        "live-verification:test",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertFalse(payload["external_write"])
            self.assertEqual(payload["date_text"], "2026-07-20")
            paths = get_paths(home)
            drafts = db.list_calendar_drafts(paths)
            self.assertEqual(len(drafts), 1)
            self.assertEqual(drafts[0]["event_id"], payload["event_id"])
            self.assertEqual(drafts[0]["source_ids"], ["live-verification:test"])
            audit = db.list_audit_events(paths)[0]
            self.assertEqual(audit["action"], "integration.seed_calendar_draft")
            self.assertEqual(audit["side_effect"], "local_db_write")

    def test_cli_integrations_require_ready_fails_when_missing_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--home", str(Path(tmp) / "home"), "integrations", "check", "--suite", "gmail", "--require-ready"])
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 1)
            self.assertNotEqual(payload["status"], "ready")

    def test_calendar_verification_requires_non_sandbox_sync_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(Path(tmp) / "home")
            ensure_dirs(paths)
            db.init_db(paths)
            db.insert_approval_record(
                paths,
                confirmation_id="sandbox-google",
                actor="sandbox",
                action="calendar.sync",
                subject="google_calendar",
                capability="calendar_write",
                side_effect="external_calendar_write",
                status="confirmed",
                evidence_refs=["gmail:sandbox"],
                metadata={"external_ids": ["sandbox-event"]},
                created_at="2026-06-10T12:00:00Z",
                consumed_at="2026-06-10T12:00:00Z",
            )

            sandbox_report = run_verification(paths, suite="calendar", persist=False)
            sandbox_checks = {check.name: check for check in sandbox_report.checks}
            self.assertEqual(sandbox_checks["google_calendar.sync_evidence"].status, "missing")

            db.insert_approval_record(
                paths,
                confirmation_id="live-google",
                actor="user",
                action="calendar.sync",
                subject="google_calendar",
                capability="calendar_write",
                side_effect="external_calendar_write",
                status="confirmed",
                evidence_refs=["gmail:live"],
                metadata={"external_ids": ["live-event"], "created_external_ids": ["live-event"]},
                created_at="2026-06-10T12:05:00Z",
                consumed_at="2026-06-10T12:05:00Z",
            )
            db.insert_approval_record(
                paths,
                confirmation_id="live-apple",
                actor="user",
                action="calendar.sync",
                subject="apple_calendar",
                capability="calendar_write",
                side_effect="external_calendar_write",
                status="confirmed",
                evidence_refs=["gmail:live"],
                metadata={"external_ids": ["apple-event"], "updated_external_ids": ["apple-event"]},
                created_at="2026-06-10T12:06:00Z",
                consumed_at="2026-06-10T12:06:00Z",
            )

            live_report = run_verification(paths, suite="calendar", persist=False)
            live_checks = {check.name: check for check in live_report.checks}
            self.assertEqual(live_checks["google_calendar.sync_evidence"].status, "ready")
            self.assertEqual(live_checks["google_calendar.sync_evidence"].metadata["latest_confirmation_id"], "live-google")
            self.assertEqual(live_checks["apple_calendar.sync_evidence"].status, "ready")
            self.assertEqual(live_checks["apple_calendar.sync_evidence"].metadata["updated_external_ids"], ["apple-event"])

    def test_cli_integrations_env_template_redacts_available_secret_values(self) -> None:
        old = os.environ.get("SENTINEL_GOOGLE_TOKEN_JSON")
        os.environ["SENTINEL_GOOGLE_TOKEN_JSON"] = '{"access_token":"template-secret-token"}'
        try:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["integrations", "env-template", "--account", "sandbox@example.com"])
        finally:
            if old is None:
                os.environ.pop("SENTINEL_GOOGLE_TOKEN_JSON", None)
            else:
                os.environ["SENTINEL_GOOGLE_TOKEN_JSON"] = old

        self.assertEqual(code, 0)
        raw = output.getvalue()
        self.assertNotIn("template-secret-token", raw)
        self.assertIn("env:SENTINEL_GOOGLE_TOKEN_JSON:***", raw)
        payload = json.loads(raw)
        token_entry = next(item for item in payload["required_env"] if item["name"] == "SENTINEL_GOOGLE_TOKEN_JSON")
        self.assertTrue(token_entry["status"]["available"])
        self.assertIn("privacy", payload)
        self.assertTrue(any("sync-gmail --account sandbox@example.com" in command for command in payload["sync_commands"]))
        self.assertTrue(any("integrations handoff" in command for command in payload["verification_commands"]))
        self.assertTrue(any("privacy audit --require-clean" in command for command in payload["verification_commands"]))
        self.assertTrue(any("privacy release-package" in command for command in payload["verification_commands"]))
        self.assertTrue(any("privacy release-audit" in command for command in payload["verification_commands"]))

    def test_live_verification_preflight_dry_run_redacts_secret_values(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["SENTINEL_LIVE_DRY_RUN"] = "1"
            env["SENTINEL_LIVE_HOME"] = str(Path(tmp) / "home")
            env["SENTINEL_LIVE_PYTHON"] = sys.executable
            env["SENTINEL_LIVE_ACCOUNT"] = "sandbox@example.com"
            env["SENTINEL_LIVE_SEED_CALENDAR_DRAFT"] = "1"
            env["SENTINEL_GOOGLE_TOKEN_JSON"] = '{"access_token":"dry-run-secret-token"}'

            result = subprocess.run(
                ["bash", str(root / "scripts" / "live_verification_preflight.sh")],
                cwd=root,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        self.assertIn("integrations env-template", combined)
        self.assertIn("integrations check --suite all", combined)
        self.assertIn("integrations seed-calendar-draft", combined)
        self.assertIn("integrations completion-audit", combined)
        self.assertIn("--source-release-path", combined)
        self.assertIn("privacy audit", combined)
        self.assertIn("privacy release-package", combined)
        self.assertIn("privacy release-audit", combined)
        self.assertIn("Skipping Gmail sync", combined)
        self.assertIn("Skipping external calendar writes", combined)
        self.assertNotIn("dry-run-secret-token", combined)

    def test_sandbox_verification_exercises_connectors_calendar_and_approvals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(
                    [
                        "--home",
                        str(home),
                        "integrations",
                        "check",
                        "--suite",
                        "sandbox",
                        "--account",
                        "sandbox@example.com",
                        "--require-ready",
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["suite"], "sandbox")
            self.assertEqual(payload["status"], "ready")
            self.assertTrue(Path(payload["artifact_path"]).exists())
            self.assertEqual(
                {check["name"] for check in payload["checks"]},
                {
                    "sandbox.gmail_sync",
                    "sandbox.google_calendar_confirmation",
                    "sandbox.apple_calendar_confirmation",
                    "sandbox.approval_records",
                },
            )
            artifact = Path(payload["artifact_path"]).read_text(encoding="utf-8")
            self.assertNotIn("token", artifact.lower())
            paths = get_paths(home)
            state = db.get_connector_state(paths, connector="gmail_api", account_id="sandbox@example.com")
            self.assertIsNotNone(state)
            self.assertEqual(state["scopes"], ["https://www.googleapis.com/auth/gmail.readonly"])
            self.assertGreaterEqual(len(db.list_approval_records(paths)), 2)
            actions = [event["action"] for event in db.list_audit_events(paths, limit=20)]
            self.assertIn("integration.verify", actions)
            self.assertIn("email.connector.sync", actions)
            self.assertIn("calendar.sync", actions)


class LiveVerificationDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = get_paths(self.tmp.name)
        ensure_dirs(self.paths)
        ensure_config(self.paths)
        db.init_db(self.paths)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def request(self, method: str, path: str) -> tuple[int, dict[str, str], bytes]:
        raw = (
            f"{method} {path} HTTP/1.1\r\n"
            "Host: live-verification-smoke\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        ).encode("ascii")
        socket = FakeSocket(raw)
        handler_class = type("LiveVerificationHandler", (Handler,), {"paths": self.paths})
        handler_class(socket, ("127.0.0.1", 0), object())
        return parse_response(socket.response.getvalue())

    def json_request(self, method: str, path: str) -> tuple[int, dict[str, str], object]:
        status, headers, body = self.request(method, path)
        return status, headers, json.loads(body.decode("utf-8"))

    def test_integration_verification_api_exposes_stored_reports(self) -> None:
        run_verification(
            self.paths,
            suite="langgraph",
            persist=True,
            created_at="2026-06-10T12:00:00Z",
        )
        status, _, reports = self.json_request("GET", "/api/integrations/verifications")
        self.assertEqual(status, 200)
        self.assertEqual(reports[0]["suite"], "langgraph")

    def test_dashboard_fetches_integration_verification_count(self) -> None:
        status, _, body = self.request("GET", "/ops")
        html = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("/api/integrations/verifications", html)
        self.assertIn('id="integrationCount"', html)


if __name__ == "__main__":
    unittest.main()
