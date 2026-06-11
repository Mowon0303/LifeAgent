from __future__ import annotations

import json
import unittest

from sentineldesk.redact import redact
from sentineldesk.reports import redact_data


class RedactTests(unittest.TestCase):
    def test_redacts_email(self) -> None:
        self.assertIn("[REDACTED_EMAIL]", redact("Contact a@example.com now"))

    def test_redacts_phone(self) -> None:
        self.assertIn("[REDACTED_PHONE]", redact("Call +1 555-010-1234"))

    def test_redacts_ssn_like_id(self) -> None:
        self.assertIn("[REDACTED_ID]", redact("SSN 123-45-6789"))

    def test_redacts_url(self) -> None:
        self.assertIn("[REDACTED_URL]", redact("Open https://example.com/private/case"))

    def test_redacts_local_filesystem_path(self) -> None:
        redacted = redact("Saved screenshot at /Users/example/.sentineldesk/artifacts/case/run.png")
        self.assertIn("[REDACTED_PATH]", redacted)
        self.assertNotIn("/Users/example", redacted)

    def test_structured_redaction_hides_email_attachments_invitees_and_connector_metadata(self) -> None:
        redacted = redact_data(
            {
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
            }
        )
        payload = json.dumps(redacted)
        self.assertIn("[REDACTED_EMAIL]", payload)
        self.assertIn("[REDACTED_SECRET]", payload)
        self.assertIn("[REDACTED_ATTACHMENT]", payload)
        self.assertIn("[REDACTED_INVITEE]", payload)
        self.assertIn("[REDACTED_CONNECTOR_METADATA]", payload)
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
            self.assertNotIn(raw_value, payload)


if __name__ == "__main__":
    unittest.main()
