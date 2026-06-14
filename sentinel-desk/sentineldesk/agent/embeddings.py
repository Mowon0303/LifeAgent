"""Local text embeddings for semantic retrieval.

The deterministic rule path keeps working with no model; embeddings are an
optional semantic layer. A real embedder (Ollama's /api/embeddings, e.g.
nomic-embed-text) is used when configured, and a dependency-free hashing
embedder backs tests and any environment without a model — same interface, so
the rest of the RAG code never needs to know which is in play.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.error
import urllib.request
from typing import Protocol

from .model import ModelProvider

DEFAULT_EMBED_MODEL = "nomic-embed-text"
EMBED_TIMEOUT_SECONDS = 30
_TOKEN_RE = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    name: str
    dimension: int

    def embed(self, text: str) -> list[float]:
        ...


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class HashEmbedder:
    """A dependency-free fallback: a hashed bag-of-words vector. Crude, but
    deterministic and good enough that texts sharing words score higher — used
    for tests and when no embedding model is available."""

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension
        self.name = f"hash-{dimension}"

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        for token in _TOKEN_RE.findall(text.lower()):
            bucket = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % self.dimension
            vec[bucket] += 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            return vec
        return [x / norm for x in vec]


class OllamaEmbedder:
    def __init__(self, *, model: str, base_url: str, timeout: int = EMBED_TIMEOUT_SECONDS) -> None:
        self.model = model
        self.base_url = (base_url or "http://127.0.0.1:11434").rstrip("/")
        self.timeout = timeout
        self.name = f"ollama:{model}"
        self.dimension = 0  # learned from the first response

    def embed(self, text: str) -> list[float]:
        payload = {"model": self.model, "prompt": text}
        request = urllib.request.Request(
            f"{self.base_url}/api/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        vector = [float(x) for x in body.get("embedding") or []]
        if vector:
            self.dimension = len(vector)
        return vector


def embedder_for(provider: ModelProvider) -> Embedder:
    """Pick a real embedder when an Ollama model is configured, else the local
    hashing fallback."""
    if provider.provider.lower() == "ollama":
        model = provider.embed_model or DEFAULT_EMBED_MODEL
        return OllamaEmbedder(model=model, base_url=provider.base_url or "http://127.0.0.1:11434")
    return HashEmbedder()
