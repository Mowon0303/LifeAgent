from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from sentineldesk.secrets import env_secret, secret_status

from .model import ModelProvider
from .schemas import AgentAnswer, Citation, Intent


class StructuredOutputError(ValueError):
    pass


@dataclass(frozen=True)
class ModelAdapterStatus:
    provider: str
    model: str
    privacy: str
    base_url: str
    structured_output: bool
    api_key: dict[str, str | bool] | None
    request_format: str


class ModelAdapter(Protocol):
    provider: ModelProvider

    def status(self) -> ModelAdapterStatus:
        ...

    def build_request(self, *, system: str, user: str) -> dict[str, Any]:
        ...


class LocalRuleAdapter:
    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def status(self) -> ModelAdapterStatus:
        return ModelAdapterStatus(
            provider=self.provider.provider,
            model=self.provider.model,
            privacy=self.provider.privacy,
            base_url=self.provider.base_url,
            structured_output=True,
            api_key=None,
            request_format="local_rule_graph",
        )

    def build_request(self, *, system: str, user: str) -> dict[str, Any]:
        return {
            "engine": "local_rule_graph",
            "model": self.provider.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "schema": agent_answer_schema(),
        }


class OllamaAdapter:
    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def status(self) -> ModelAdapterStatus:
        return ModelAdapterStatus(
            provider="ollama",
            model=self.provider.model,
            privacy=self.provider.privacy or "local-network",
            base_url=self.provider.base_url or "http://127.0.0.1:11434",
            structured_output=self.provider.structured_output,
            api_key=None,
            request_format="ollama_chat_json",
        )

    def build_request(self, *, system: str, user: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.provider.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
        }
        if self.provider.structured_output:
            payload["format"] = "json"
            payload["schema"] = agent_answer_schema()
        return {"url": f"{self.status().base_url.rstrip('/')}/api/chat", "json": payload}


class OpenAIAdapter:
    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def status(self) -> ModelAdapterStatus:
        return _cloud_status(self.provider, provider_name="openai", base_url=self.provider.base_url or "https://api.openai.com/v1")

    def build_request(self, *, system: str, user: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.provider.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self.provider.structured_output:
            payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "agent_answer", "schema": agent_answer_schema()}}
        return {"url": f"{self.status().base_url.rstrip('/')}/chat/completions", "json": payload}


class AnthropicAdapter:
    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def status(self) -> ModelAdapterStatus:
        return _cloud_status(self.provider, provider_name="anthropic", base_url=self.provider.base_url or "https://api.anthropic.com")

    def build_request(self, *, system: str, user: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.provider.model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": 1200,
        }
        if self.provider.structured_output:
            payload["metadata"] = {"expected_schema": "agent_answer"}
        return {"url": f"{self.status().base_url.rstrip('/')}/v1/messages", "json": payload, "schema": agent_answer_schema()}


def adapter_for(provider: ModelProvider) -> ModelAdapter:
    normalized = provider.provider.lower()
    if normalized == "ollama":
        return OllamaAdapter(provider)
    if normalized == "openai":
        return OpenAIAdapter(provider)
    if normalized == "anthropic":
        return AnthropicAdapter(provider)
    return LocalRuleAdapter(provider)


def adapter_status_dict(provider: ModelProvider) -> dict[str, Any]:
    return asdict(adapter_for(provider).status())


def validate_agent_answer_payload(payload: dict[str, Any]) -> AgentAnswer:
    if not isinstance(payload, dict):
        raise StructuredOutputError("structured output must be a JSON object")
    try:
        intent = Intent(str(payload["intent"]))
    except KeyError as exc:
        raise StructuredOutputError("missing required field: intent") from exc
    except ValueError as exc:
        raise StructuredOutputError(f"unknown intent: {payload.get('intent')}") from exc
    answer = str(payload.get("answer") or "").strip()
    if not answer:
        raise StructuredOutputError("missing required field: answer")
    confidence = str(payload.get("confidence") or "").strip().lower()
    if confidence not in {"uncertain", "low", "medium", "high"}:
        raise StructuredOutputError("confidence must be one of uncertain, low, medium, high")
    citations = tuple(_citation_from_payload(item) for item in payload.get("citations", []) or [])
    tool_calls = tuple(str(item) for item in payload.get("tool_calls", []) or [])
    return AgentAnswer(
        intent=intent,
        answer=answer,
        confidence=confidence,
        citations=citations,
        tool_calls=tool_calls,
        requires_confirmation=bool(payload.get("requires_confirmation", False)),
        uncertain=bool(payload.get("uncertain", confidence == "uncertain")),
        metadata=dict(payload.get("metadata") or {}),
    )


def agent_answer_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["intent", "answer", "confidence"],
        "properties": {
            "intent": {"type": "string", "enum": [item.value for item in Intent]},
            "answer": {"type": "string"},
            "confidence": {"type": "string", "enum": ["uncertain", "low", "medium", "high"]},
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["source_id", "source_type"],
                    "additionalProperties": False,
                    "properties": {
                        "source_id": {"type": "string"},
                        "source_type": {"type": "string"},
                        "evidence": {"type": "string"},
                        "captured_at": {"type": "string"},
                    },
                },
            },
            "tool_calls": {"type": "array", "items": {"type": "string"}},
            "requires_confirmation": {"type": "boolean"},
            "uncertain": {"type": "boolean"},
            "metadata": {"type": "object"},
        },
    }


def _cloud_status(model_provider: ModelProvider, *, provider_name: str, base_url: str) -> ModelAdapterStatus:
    api_key = secret_status(env_secret(model_provider.api_key_env)) if model_provider.api_key_env else None
    return ModelAdapterStatus(
        provider=provider_name,
        model=model_provider.model,
        privacy="cloud-visible" if model_provider.privacy in {"", "local-first"} else model_provider.privacy,
        base_url=base_url,
        structured_output=model_provider.structured_output,
        api_key=api_key,
        request_format=f"{provider_name}_chat_json",
    )


def _citation_from_payload(payload: Any) -> Citation:
    if not isinstance(payload, dict):
        raise StructuredOutputError("citation entries must be JSON objects")
    source_id = str(payload.get("source_id") or "").strip()
    source_type = str(payload.get("source_type") or "").strip()
    if not source_id or not source_type:
        raise StructuredOutputError("citation entries require source_id and source_type")
    return Citation(
        source_id=source_id,
        source_type=source_type,
        evidence=str(payload.get("evidence") or ""),
        captured_at=str(payload.get("captured_at") or ""),
    )
