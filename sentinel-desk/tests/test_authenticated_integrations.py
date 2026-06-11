from __future__ import annotations

import contextlib
import json
import os
import io
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sentineldesk import db
from sentineldesk.calendar.adapters import AppleCalendarAdapter, GoogleCalendarAdapter, sync_calendar_draft
from sentineldesk.calendar.models import CalendarDraft, DeadlineEvent
from sentineldesk.cli import main
from sentineldesk.config import get_paths
from sentineldesk.email.connectors import EmailSyncRequest, GmailApiEmailConnector
from sentineldesk.email.ingest import sync_connector
from sentineldesk.integrations.apple_calendar import AppleCalendarConfig
from sentineldesk.integrations.google_oauth import GoogleTokenWriteResult, write_google_oauth_token
from sentineldesk.integrations.google_workspace import GMAIL_READONLY_SCOPE, GoogleOAuthConfig
from sentineldesk.secrets import env_secret, resolve_secret, secret_status


class AuthenticatedIntegrationTests(unittest.TestCase):
    def test_secret_refs_resolve_from_env_and_redact(self) -> None:
        name = "SENTINEL_TEST_SECRET"
        old = os.environ.get(name)
        os.environ[name] = '{"token":"hidden"}'
        try:
            ref = env_secret(name)
            self.assertEqual(resolve_secret(ref), '{"token":"hidden"}')
            self.assertEqual(secret_status(ref)["redacted"], f"env:{name}:***")
            self.assertNotIn("hidden", str(secret_status(ref)))
        finally:
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old

    def test_google_oauth_config_safe_summary_never_exposes_secret_values(self) -> None:
        config = GoogleOAuthConfig(
            credentials_json=env_secret("GOOGLE_CREDS"),
            token_json=env_secret("GOOGLE_TOKEN"),
            scopes=(GMAIL_READONLY_SCOPE,),
            account_id="me@example.com",
        )
        summary = config.safe_summary()
        self.assertEqual(summary["account_id"], "me@example.com")
        self.assertIn(GMAIL_READONLY_SCOPE, summary["scopes"])
        self.assertEqual(summary["credentials"], "env:GOOGLE_CREDS:***")
        self.assertEqual(summary["token"], "env:GOOGLE_TOKEN:***")

    def test_gmail_authenticated_sync_saves_incremental_cursor_and_audits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(Path(tmp) / "home")
            client = FakeGmailClient()
            summary = sync_connector(
                paths,
                GmailApiEmailConnector(client),
                EmailSyncRequest(query="deadline", since="history-0", limit=5),
                account_id="me@example.com",
                ingested_at="2026-06-10T12:00:00Z",
            )
            self.assertEqual(summary["connector"], "gmail_api")
            self.assertTrue(summary["cursor_saved"])
            self.assertEqual(client.calls[0], {"query": "deadline", "since": "history-0", "limit": 5})

            state = db.get_connector_state(paths, connector="gmail_api", account_id="me@example.com")
            self.assertIsNotNone(state)
            self.assertEqual(state["cursor"], "history-123")
            self.assertEqual(state["scopes"], [GMAIL_READONLY_SCOPE])
            self.assertEqual(state["metadata"]["raw_count"], 1)
            actions = [event["action"] for event in db.list_audit_events(paths)]
            self.assertIn("email.connector.sync", actions)
            self.assertIn("email.ingest", actions)

    def test_remote_calendar_clients_are_confirmation_gated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(Path(tmp) / "home")
            event = DeadlineEvent("Deadline: Notice", "2026-07-02", ("gmail:gmail-1",))
            draft = CalendarDraft((event,))

            google_client = FakeCalendarClient("google-event")
            google_adapter = GoogleCalendarAdapter(google_client)
            blocked = sync_calendar_draft(paths, draft, google_adapter, confirmed=False, actor="test")
            self.assertFalse(blocked.allowed)
            self.assertEqual(google_client.created, [])

            allowed = sync_calendar_draft(paths, draft, google_adapter, confirmed=True, confirmation_id="ok-google", actor="test")
            self.assertTrue(allowed.allowed)
            self.assertEqual(allowed.external_ids, ("google-event",))
            self.assertEqual(google_client.created[0]["calendar_id"], "primary")

            apple_client = FakeCalendarClient("apple-event")
            apple_adapter = AppleCalendarAdapter(apple_client, calendar_id="icloud-main")
            allowed_apple = sync_calendar_draft(paths, draft, apple_adapter, confirmed=True, confirmation_id="ok-apple", actor="test")
            self.assertTrue(allowed_apple.allowed)
            self.assertEqual(allowed_apple.external_ids, ("apple-event",))
            self.assertEqual(apple_client.created[0]["calendar_id"], "icloud-main")

    def test_remote_calendar_clients_dedupe_and_update_before_create(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = get_paths(Path(tmp) / "home")
            existing = DeadlineEvent("Deadline: Notice", "2026-07-02", ("gmail:gmail-1",))
            new = DeadlineEvent("Deadline: Rent", "2026-07-05", ("gmail:gmail-2",))
            draft = CalendarDraft((existing, new))
            client = FakeUpsertCalendarClient(
                existing=[
                    {
                        "id": "remote-existing",
                        "lifeagent_event_id": existing.event_id,
                        "summary": existing.title,
                        "start": {"date": existing.date_text},
                    }
                ]
            )

            result = sync_calendar_draft(
                paths,
                draft,
                GoogleCalendarAdapter(client),
                confirmed=True,
                confirmation_id="ok-upsert",
                actor="test",
            )

            self.assertTrue(result.allowed)
            self.assertEqual(result.updated_external_ids, ("remote-existing",))
            self.assertEqual(result.created_external_ids, ("remote-created-1",))
            self.assertEqual(client.updated[0]["event_id"], "remote-existing")
            self.assertEqual(client.created[0]["event_id"], new.event_id)
            approval = db.list_approval_records(paths)[0]
            self.assertEqual(approval["metadata"]["updated_external_ids"], ["remote-existing"])
            self.assertEqual(approval["metadata"]["created_external_ids"], ["remote-created-1"])

    def test_apple_calendar_config_safe_summary_redacts_app_password(self) -> None:
        config = AppleCalendarConfig(
            username=env_secret("APPLE_USER"),
            app_password=env_secret("APPLE_APP_PASSWORD"),
            account_id="icloud",
        )
        summary = config.safe_summary()
        self.assertEqual(summary["username"], "env:APPLE_USER:***")
        self.assertEqual(summary["app_password"], "env:APPLE_APP_PASSWORD:***")

    def test_google_oauth_token_writer_never_returns_token_value(self) -> None:
        name = "SENTINEL_TEST_GOOGLE_CREDS"
        old = os.environ.get(name)
        os.environ[name] = '{"installed":{"client_id":"client","client_secret":"secret","redirect_uris":["http://localhost"]}}'
        try:
            with tempfile.TemporaryDirectory() as tmp:
                output_path = Path(tmp) / "google-token.json"
                result = write_google_oauth_token(
                    credentials_ref=env_secret(name),
                    output_path=output_path,
                    token_env="SENTINEL_TEST_GOOGLE_TOKEN",
                    scopes=(GMAIL_READONLY_SCOPE,),
                    port=0,
                    open_browser=False,
                    flow_factory=FakeInstalledAppFlow,
                )
                raw_result = str(result.to_dict())
                self.assertNotIn("oauth-secret-token", raw_result)
                self.assertIn("env:SENTINEL_TEST_GOOGLE_TOKEN:***", raw_result)
                self.assertEqual(stat.S_IMODE(output_path.stat().st_mode), 0o600)
                self.assertIn("oauth-secret-token", output_path.read_text(encoding="utf-8"))
                self.assertIn("$(cat", result.export_hint)
        finally:
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old

    def test_cli_google_token_command_redacts_token_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "token.json"
            result = GoogleTokenWriteResult(
                output_path=str(token_path),
                output_mode="0o600",
                token_env="SENTINEL_GOOGLE_TOKEN_JSON",
                token_env_ref="env:SENTINEL_GOOGLE_TOKEN_JSON:***",
                export_hint=f'export SENTINEL_GOOGLE_TOKEN_JSON="$(cat {token_path})"',
                scopes=(GMAIL_READONLY_SCOPE,),
                flow="fake",
                open_browser=False,
                port=0,
            )
            with patch("sentineldesk.cli.write_google_oauth_token", return_value=result) as writer:
                output = io.StringIO()
                with patch("sys.stdout", output):
                    code = main(
                        [
                            "--home",
                            str(Path(tmp) / "home"),
                            "integrations",
                            "google-token",
                            "--credentials-env",
                            "SENTINEL_TEST_GOOGLE_CREDS",
                            "--token-output",
                            str(token_path),
                            "--scope",
                            "gmail.readonly",
                            "--no-browser",
                        ]
                    )
                raw = output.getvalue()
            self.assertEqual(code, 0)
            self.assertNotIn("oauth-secret-token", raw)
            self.assertIn("env:SENTINEL_GOOGLE_TOKEN_JSON:***", raw)
            writer.assert_called_once()
            self.assertEqual(writer.call_args.kwargs["credentials_ref"].name, "SENTINEL_TEST_GOOGLE_CREDS")
            self.assertEqual(writer.call_args.kwargs["scopes"], (GMAIL_READONLY_SCOPE,))

    def test_cli_calendar_sync_preview_blocks_google_without_secret_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            paths = get_paths(home)
            event = DeadlineEvent("Deadline: Notice", "2026-07-02", ("gmail:gmail-1",))
            db.init_db(paths)
            db.upsert_calendar_draft(paths, event=event, created_at="2026-06-10T12:00:00Z")

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--home", str(home), "calendar", "sync", "--destination", "google"])

            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertFalse(payload["allowed"])
            self.assertEqual(payload["reason"], "calendar_write_requires_confirmation")
            self.assertEqual(db.list_calendar_drafts(paths)[0]["sync_state"], "local_draft")
            self.assertEqual(db.list_audit_events(paths)[0]["action"], "calendar.sync.blocked")

    def test_cli_calendar_sync_google_confirmed_updates_draft_and_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            paths = get_paths(home)
            event = DeadlineEvent("Deadline: Notice", "2026-07-02", ("gmail:gmail-1",))
            db.init_db(paths)
            db.upsert_calendar_draft(paths, event=event, created_at="2026-06-10T12:00:00Z")

            output = io.StringIO()
            with patch("sentineldesk.cli.GoogleWorkspaceFactory", FakeGoogleWorkspaceFactory):
                with contextlib.redirect_stdout(output):
                    code = main(
                        [
                            "--home",
                            str(home),
                            "calendar",
                            "sync",
                            "--destination",
                            "google",
                            "--confirm",
                            "--confirmation-id",
                            "ok-google-live",
                            "--calendar-id",
                            "sandbox-calendar",
                        ]
                    )

            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["allowed"])
            self.assertEqual(payload["created_external_ids"], ["google-event"])
            draft_row = db.list_calendar_drafts(paths)[0]
            self.assertEqual(draft_row["sync_state"], "google_synced")
            self.assertEqual(draft_row["status"], "synced")
            approval = db.list_approval_records(paths)[0]
            self.assertEqual(approval["confirmation_id"], "ok-google-live")
            self.assertEqual(approval["subject"], "google_calendar")

    def test_cli_calendar_edit_reopens_synced_draft_as_local_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            paths = get_paths(home)
            event = DeadlineEvent("Deadline: Notice", "2026-07-02", ("gmail:gmail-1",))
            db.init_db(paths)
            db.upsert_calendar_draft(paths, event=event, created_at="2026-06-10T12:00:00Z")
            db.update_calendar_draft_sync_state(
                paths,
                event_id=event.event_id,
                sync_state="google_synced",
                status="synced",
                updated_at="2026-06-10T12:05:00Z",
            )

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(
                    [
                        "--home",
                        str(home),
                        "calendar",
                        "edit",
                        "--event-id",
                        event.event_id,
                        "--date",
                        "2026-07-03",
                        "--severity",
                        "critical",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertFalse(payload["external_write"])
            updated = db.list_calendar_drafts(paths)[0]
            self.assertEqual(updated["date_text"], "2026-07-03")
            self.assertEqual(updated["severity"], "critical")
            self.assertEqual(updated["status"], "draft")
            self.assertEqual(updated["sync_state"], "local_draft")
            self.assertEqual(db.list_approval_records(paths), [])
            audit = db.list_audit_events(paths)[0]
            self.assertEqual(audit["action"], "calendar.edit")
            self.assertEqual(audit["side_effect"], "local_db_write")
            self.assertFalse(audit["metadata"]["external_write"])

    def test_cli_calendar_sync_external_confirm_requires_confirmation_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            paths = get_paths(home)
            event = DeadlineEvent("Deadline: Notice", "2026-07-02", ("gmail:gmail-1",))
            db.init_db(paths)
            db.upsert_calendar_draft(paths, event=event, created_at="2026-06-10T12:00:00Z")

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--home", str(home), "calendar", "sync", "--destination", "apple", "--confirm"])

            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output.getvalue())["error"], "external calendar sync requires --confirmation-id")
            self.assertEqual(db.list_approval_records(paths), [])

    def test_cli_calendar_sync_apple_confirmed_uses_default_calendar_and_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            paths = get_paths(home)
            event = DeadlineEvent("Deadline: Notice", "2026-07-02", ("gmail:gmail-1",))
            db.init_db(paths)
            db.upsert_calendar_draft(paths, event=event, created_at="2026-06-10T12:00:00Z")

            output = io.StringIO()
            with patch("sentineldesk.cli.AppleCalendarClientFactory", FakeAppleCalendarClientFactory):
                with contextlib.redirect_stdout(output):
                    code = main(
                        [
                            "--home",
                            str(home),
                            "calendar",
                            "sync",
                            "--destination",
                            "apple",
                            "--confirm",
                            "--confirmation-id",
                            "ok-apple-live",
                        ]
                    )

            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["allowed"])
            self.assertEqual(payload["created_external_ids"], ["apple-event"])
            approval = db.list_approval_records(paths)[0]
            self.assertEqual(approval["confirmation_id"], "ok-apple-live")
            self.assertEqual(approval["subject"], "apple_calendar")
            self.assertEqual(approval["metadata"]["destination"], "apple_calendar")


class FakeGmailClient:
    account_id = "me@example.com"
    scopes = (GMAIL_READONLY_SCOPE,)

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def search_messages(self, query: str, since: str, limit: int) -> dict[str, object]:
        self.calls.append({"query": query, "since": since, "limit": limit})
        return {
            "cursor": "history-123",
            "raw_count": 1,
            "messages": [
                {
                    "id": "gmail-1",
                    "thread_id": "thread-1",
                    "from": "school@example.com",
                    "subject": "Form deadline",
                    "date": "2026-06-10",
                    "body": "Submit the form by July 15, 2026.",
                }
            ],
        }


class FakeGoogleWorkspaceFactory:
    def __init__(self, config: GoogleOAuthConfig) -> None:
        self.config = config

    def calendar_client(self, calendar_id: str = "primary") -> "FakeCalendarClient":
        self.calendar_id = calendar_id
        return FakeCalendarClient("google-event")


class FakeAppleCalendarClientFactory:
    def __init__(self, config: AppleCalendarConfig) -> None:
        self.config = config

    def calendar_client(self) -> "FakeCalendarClient":
        return FakeCalendarClient("apple-event")


class FakeCalendarClient:
    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        self.created: list[dict[str, object]] = []

    def create_event(self, calendar_id: str, event: DeadlineEvent) -> dict[str, str]:
        self.created.append({"calendar_id": calendar_id, "event_id": event.event_id})
        return {"id": self.event_id}


class FakeUpsertCalendarClient:
    def __init__(self, existing: list[dict[str, object]]) -> None:
        self.existing = existing
        self.created: list[dict[str, object]] = []
        self.updated: list[dict[str, object]] = []

    def list_events(self, calendar_id: str) -> list[dict[str, object]]:
        return list(self.existing)

    def update_event(self, calendar_id: str, event_id: str, event: DeadlineEvent) -> dict[str, str]:
        self.updated.append({"calendar_id": calendar_id, "event_id": event_id, "lifeagent_event_id": event.event_id})
        return {"id": event_id}

    def create_event(self, calendar_id: str, event: DeadlineEvent) -> dict[str, str]:
        self.created.append({"calendar_id": calendar_id, "event_id": event.event_id})
        return {"id": f"remote-created-{len(self.created)}"}


class FakeInstalledAppFlow:
    config: dict[str, object] = {}
    scopes: list[str] = []

    @classmethod
    def from_client_config(cls, config: dict[str, object], scopes: list[str]) -> "FakeInstalledAppFlow":
        cls.config = config
        cls.scopes = scopes
        return cls()

    def run_local_server(self, *, port: int, open_browser: bool) -> "FakeCredentials":
        self.port = port
        self.open_browser = open_browser
        return FakeCredentials()


class FakeCredentials:
    def to_json(self) -> str:
        return '{"token":"oauth-secret-token","refresh_token":"refresh-secret"}'


if __name__ == "__main__":
    unittest.main()
