from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sentineldesk import db
from sentineldesk.config import Paths
from sentineldesk.monitor import run_all


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    capability: str
    side_effect: str
    requires_confirmation: bool
    handler: Callable[..., Any] | None = None
    audit_required: bool = True
    trust_boundary: str = "local"

    @property
    def can_write_without_confirmation(self) -> bool:
        return self.side_effect == "none" or not self.requires_confirmation


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def names_for_capability(self, capability: str) -> list[str]:
        return [name for name, spec in sorted(self._tools.items()) if spec.capability == capability]

    def assert_can_call(self, name: str, *, confirmed: bool = False) -> ToolSpec:
        spec = self.get(name)
        if spec.requires_confirmation and not confirmed:
            raise PermissionError(f"Tool {name!r} requires confirmation before {spec.side_effect}.")
        return spec

    def call(self, name: str, *, confirmed: bool = False, **kwargs: Any) -> Any:
        spec = self.assert_can_call(name, confirmed=confirmed)
        if spec.handler is None:
            raise RuntimeError(f"Tool {name!r} has no handler bound.")
        return spec.handler(**kwargs)

    def list(self) -> list[ToolSpec]:
        return [self._tools[name] for name in sorted(self._tools)]


def default_tool_registry(paths: Paths | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="search_latest_email",
            description="Search recent email threads for deadlines, amounts, and required actions.",
            capability="email_read",
            side_effect="none",
            requires_confirmation=False,
        )
    )
    registry.register(
        ToolSpec(
            name="parse_attachments",
            description="Parse local or email attachments for evidence.",
            capability="document_read",
            side_effect="none",
            requires_confirmation=False,
        )
    )
    registry.register(
        ToolSpec(
            name="search_policy_docs",
            description="Search the local RAG index for trusted policy or explanation documents.",
            capability="document_read",
            side_effect="none",
            requires_confirmation=False,
            handler=_search_policy_docs(paths) if paths is not None else None,
        )
    )
    registry.register(
        ToolSpec(
            name="search_email_rag",
            description="Semantically search the user's email (hybrid embedding + keyword) for context.",
            capability="email_read",
            side_effect="none",
            requires_confirmation=False,
            handler=_search_email_rag(paths) if paths is not None else None,
        )
    )
    registry.register(
        ToolSpec(
            name="capture_latest_portal",
            description="Capture latest portal state through a configured target.",
            capability="portal_read",
            side_effect="local_evidence_write",
            requires_confirmation=False,
            handler=_capture_latest_portal(paths) if paths is not None else None,
            trust_boundary="portal",
        )
    )
    registry.register(
        ToolSpec(
            name="read_evidence_bundle",
            description="Read a local evidence bundle for a prior run.",
            capability="evidence_read",
            side_effect="none",
            requires_confirmation=False,
            handler=_read_latest_evidence(paths) if paths is not None else None,
        )
    )
    registry.register(
        ToolSpec(
            name="draft_calendar_event",
            description="Create a local draft calendar event from verified evidence.",
            capability="calendar_draft",
            side_effect="local_draft",
            requires_confirmation=False,
        )
    )
    registry.register(
        ToolSpec(
            name="sync_calendar_event",
            description="Write confirmed deadline events to an external calendar.",
            capability="calendar_write",
            side_effect="external_calendar_write",
            requires_confirmation=True,
        )
    )
    return registry


def _capture_latest_portal(paths: Paths) -> Callable[..., dict[str, Any]]:
    def handler(target_name: str | None = None) -> dict[str, Any]:
        db.init_db(paths)
        runs = run_all(paths, name=target_name)
        return {
            "runs": runs,
            "run_count": len(runs),
            "target_name": target_name or "",
        }

    return handler


def _read_latest_evidence(paths: Paths) -> Callable[..., dict[str, Any]]:
    def handler(limit: int = 1) -> dict[str, Any]:
        db.init_db(paths)
        runs = db.list_runs(paths, limit=limit)
        return {
            "runs": runs,
            "run_count": len(runs),
        }

    return handler


def _search_email_rag(paths: Paths) -> Callable[..., dict[str, Any]]:
    def handler(query: str, limit: int = 4) -> dict[str, Any]:
        from sentineldesk.agent.embeddings import embedder_for
        from sentineldesk.agent.model import load_model_provider
        from sentineldesk.agent.rag_index import hybrid_search

        db.init_db(paths)
        embedder = embedder_for(load_model_provider(paths))
        results = hybrid_search(paths, query, embedder, limit=limit)
        return {
            "documents": [
                {
                    "source_id": str(document.metadata.get("document_source_id") or document.source_id),
                    "source_type": document.source_type,
                    "trust_label": document.trust_label,
                    "text": document.text,
                    "title": str(document.metadata.get("title") or ""),
                    "metadata": dict(document.metadata),
                }
                for document in results
            ],
            "document_count": len(results),
        }

    return handler


def _search_policy_docs(paths: Paths) -> Callable[..., dict[str, Any]]:
    def handler(query: str, limit: int = 3) -> dict[str, Any]:
        from sentineldesk.agent.rag_index import search_index

        db.init_db(paths)
        results = search_index(paths, query, limit=limit)
        return {
            "documents": [
                {
                    "source_id": document.source_id,
                    "source_type": document.source_type,
                    "trust_label": document.trust_label,
                    "text": document.text,
                    "warnings": list(document.warnings),
                    "metadata": dict(document.metadata),
                }
                for document in results
            ],
            "document_count": len(results),
        }

    return handler
