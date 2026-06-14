"""Verification result dataclasses and shared constants."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_SOURCE_RELEASE_PATH = "/tmp/extracted-sentineldesk"


@dataclass(frozen=True)
class VerificationCheck:
    name: str
    status: str
    detail: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class VerificationReport:
    verification_id: str
    suite: str
    status: str
    checks: tuple[VerificationCheck, ...]
    artifact_path: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "verification_id": self.verification_id,
            "suite": self.suite,
            "status": self.status,
            "checks": [asdict(check) for check in self.checks],
            "artifact_path": self.artifact_path,
            "created_at": self.created_at,
        }
