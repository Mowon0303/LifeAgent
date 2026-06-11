from __future__ import annotations

import os
from dataclasses import dataclass


class SecretUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class SecretRef:
    kind: str
    name: str

    @property
    def redacted(self) -> str:
        return f"{self.kind}:{self.name}:***"


def env_secret(name: str) -> SecretRef:
    return SecretRef("env", name)


def resolve_secret(ref: SecretRef) -> str:
    if ref.kind != "env":
        raise SecretUnavailable(f"Unsupported secret reference kind: {ref.kind}")
    value = os.environ.get(ref.name)
    if not value:
        raise SecretUnavailable(f"Missing required environment secret: {ref.name}")
    return value


def secret_status(ref: SecretRef) -> dict[str, str | bool]:
    return {
        "kind": ref.kind,
        "name": ref.name,
        "available": bool(os.environ.get(ref.name)) if ref.kind == "env" else False,
        "redacted": ref.redacted,
    }
