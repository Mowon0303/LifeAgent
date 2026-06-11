from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from sentineldesk.calendar.models import DeadlineEvent
from sentineldesk.calendar.sync import export_ics
from sentineldesk.secrets import SecretRef, resolve_secret


APPLE_CALDAV_URL = "https://caldav.icloud.com"


class AppleCalendarUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class AppleCalendarConfig:
    username: SecretRef
    app_password: SecretRef
    account_id: str = "icloud"
    caldav_url: str = APPLE_CALDAV_URL

    def safe_summary(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "caldav_url": self.caldav_url,
            "username": self.username.redacted,
            "app_password": self.app_password.redacted,
        }


class AppleCalendarClientFactory:
    def __init__(self, config: AppleCalendarConfig) -> None:
        self.config = config

    def calendar_client(self) -> "AppleCalDavClient":
        caldav = _import("caldav")
        client = caldav.DAVClient(
            url=self.config.caldav_url,
            username=resolve_secret(self.config.username),
            password=resolve_secret(self.config.app_password),
        )
        return AppleCalDavClient(client)


class AppleCalDavClient:
    def __init__(self, client: Any) -> None:
        self.client = client

    def create_event(self, calendar_id: str, event: DeadlineEvent) -> dict[str, Any]:
        principal = self.client.principal()
        calendars = principal.calendars()
        target = calendars[0] if calendar_id == "default" else _find_calendar(calendars, calendar_id)
        saved = target.save_event(export_ics([event]))
        return {"id": str(getattr(saved, "url", saved))}


def _find_calendar(calendars: list[Any], calendar_id: str) -> Any:
    for calendar in calendars:
        if str(getattr(calendar, "url", "")) == calendar_id or str(getattr(calendar, "name", "")) == calendar_id:
            return calendar
    raise AppleCalendarUnavailable(f"Apple calendar not found: {calendar_id}")


def _import(module_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise AppleCalendarUnavailable(f"Optional CalDAV dependency missing: {module_name}") from exc
