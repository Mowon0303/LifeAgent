"""Stateless request/response helpers shared by the route handlers."""

from __future__ import annotations

import json


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")


ASK_HISTORY_TURNS = 3


def sanitize_ask_history(raw: object) -> list[dict[str, str]]:
    """Keep only the last few turns and only their question + intent — the
    context the follow-up resolver needs, not the whole transcript or card data.
    """
    if not isinstance(raw, list):
        return []
    turns: list[dict[str, str]] = []
    for item in raw[-ASK_HISTORY_TURNS:]:
        if not isinstance(item, dict):
            continue
        turns.append(
            {
                "question": str(item.get("question") or "")[:300],
                "intent": str(item.get("intent") or ""),
            }
        )
    return turns


def query_int(query: dict[str, list[str]], name: str, default: int) -> int:
    try:
        return max(0, int(query.get(name, [str(default)])[0]))
    except (TypeError, ValueError):
        return default


def body_int(body: dict[str, object], name: str, default: int) -> int:
    try:
        return max(0, int(body.get(name, default)))
    except (TypeError, ValueError):
        return default


def truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "y", "on"}
