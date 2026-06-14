from __future__ import annotations

import importlib.util
import tomllib
from dataclasses import dataclass
from typing import Any

from sentineldesk.config import Paths


@dataclass(frozen=True)
class ModelProvider:
    provider: str = "local"
    model: str = "rule-router"
    base_url: str = ""
    api_key_env: str = ""
    privacy: str = "local-first"
    structured_output: bool = True
    # "free_refine" drops the fail-loud guardrails on the model rewrite (the
    # anchor check, the uncertain/confirmation skips) and lets it synthesize a
    # natural report grounded in the evidence. Opt-in, for experimentation —
    # tighten back up before relying on it.
    free_refine: bool = False
    embed_model: str = "nomic-embed-text"
    langchain_available: bool = False
    langgraph_available: bool = False


def detect_model_provider(provider: str = "local", model: str = "rule-router") -> ModelProvider:
    return ModelProvider(
        provider=provider,
        model=model,
        api_key_env=_default_api_key_env(provider),
        langchain_available=importlib.util.find_spec("langchain_core") is not None,
        langgraph_available=importlib.util.find_spec("langgraph") is not None,
    )


def load_model_provider(paths: Paths) -> ModelProvider:
    config = _load_config(paths)
    model_config = config.get("model", {}) if isinstance(config, dict) else {}
    provider = str(model_config.get("provider") or "local")
    model = str(model_config.get("model") or "rule-router")
    return ModelProvider(
        provider=provider,
        model=model,
        base_url=str(model_config.get("base_url") or ""),
        api_key_env=str(model_config.get("api_key_env") or _default_api_key_env(provider)),
        privacy=str(model_config.get("privacy") or _default_privacy(provider)),
        structured_output=bool(model_config.get("structured_output", True)),
        free_refine=bool(model_config.get("free_refine"))
        or str(model_config.get("refine") or "").lower() == "free",
        embed_model=str(model_config.get("embed_model") or "nomic-embed-text"),
        langchain_available=importlib.util.find_spec("langchain_core") is not None,
        langgraph_available=importlib.util.find_spec("langgraph") is not None,
    )


def _load_config(paths: Paths) -> dict[str, Any]:
    if not paths.config.exists():
        return {}
    try:
        return tomllib.loads(paths.config.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}


def _default_api_key_env(provider: str) -> str:
    normalized = provider.lower()
    if normalized == "openai":
        return "OPENAI_API_KEY"
    if normalized == "anthropic":
        return "ANTHROPIC_API_KEY"
    return ""


def _default_privacy(provider: str) -> str:
    normalized = provider.lower()
    if normalized in {"openai", "anthropic"}:
        return "cloud-visible"
    if normalized == "ollama":
        return "local-network"
    return "local-first"
