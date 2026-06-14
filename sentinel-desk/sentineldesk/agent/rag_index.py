from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sentineldesk import db
from sentineldesk.email.attachments import parse_attachment_file
from sentineldesk.config import Paths
from sentineldesk.extract import utc_now

from .embeddings import Embedder, cosine
from .retrieval import RetrievedDocument, search_documents, sanitize_document


@dataclass(frozen=True)
class IndexedDocument:
    source_id: str
    chunk_count: int
    warnings: tuple[str, ...]


def index_document(
    paths: Paths,
    document: RetrievedDocument,
    *,
    title: str = "",
    metadata: dict[str, Any] | None = None,
    chunk_size: int = 900,
    indexed_at: str | None = None,
    embedder: "Embedder | None" = None,
) -> IndexedDocument:
    db.init_db(paths)
    timestamp = indexed_at or utc_now()
    safe_document = sanitize_document(document)
    chunks = _chunk_text(safe_document.text, source_id=safe_document.source_id, chunk_size=chunk_size)
    chunk_payload: list[dict[str, Any]] = []
    for chunk_id, text in chunks:
        item: dict[str, Any] = {
            "chunk_id": chunk_id,
            "text": text,
            "warnings": safe_document.warnings,
            "token_count": len(text.split()),
        }
        if embedder is not None:
            item["embedding"] = embedder.embed(text)
        chunk_payload.append(item)
    db.upsert_rag_document(
        paths,
        source_id=safe_document.source_id,
        source_type=safe_document.source_type,
        trust_label=safe_document.trust_label,
        title=title or safe_document.source_id,
        metadata=metadata or {},
        chunks=chunk_payload,
        indexed_at=timestamp,
    )
    db.insert_audit_event(
        paths,
        action="rag.index",
        actor="system",
        subject=safe_document.source_id,
        capability="document_read",
        side_effect="local_db_write",
        allowed=True,
        confirmation_id="",
        metadata={"chunk_count": len(chunks), "warnings": list(safe_document.warnings)},
        created_at=timestamp,
    )
    return IndexedDocument(safe_document.source_id, len(chunks), safe_document.warnings)


def index_file(
    paths: Paths,
    file_path: str | Path,
    *,
    source_id: str | None = None,
    source_type: str = "local_doc",
    trust_label: str = "user_imported",
    title: str = "",
    metadata: dict[str, Any] | None = None,
    indexed_at: str | None = None,
) -> IndexedDocument:
    parsed = parse_attachment_file(file_path)
    resolved_source_id = source_id or f"file:{_stable_id(str(Path(file_path).resolve()))}"
    file_metadata = {"file_name": parsed.name, "content_type": parsed.content_type}
    if metadata:
        file_metadata.update(metadata)
    document = RetrievedDocument(
        source_id=resolved_source_id,
        source_type=source_type,
        text=parsed.text,
        trust_label=trust_label,
        warnings=parsed.warnings,
        metadata=file_metadata,
    )
    return index_document(
        paths,
        document,
        title=title or parsed.name,
        metadata=file_metadata,
        indexed_at=indexed_at,
    )


def _chunk_to_document(chunk: dict[str, Any]) -> RetrievedDocument:
    return RetrievedDocument(
        source_id=str(chunk["chunk_id"]),
        source_type=str(chunk["source_type"]),
        text=str(chunk["text"]),
        trust_label=str(chunk["trust_label"]),
        warnings=tuple(chunk.get("warnings", []) if isinstance(chunk.get("warnings"), list) else []),
        metadata={
            **(dict(chunk.get("metadata") or {}) if isinstance(chunk.get("metadata"), dict) else {}),
            "document_source_id": str(chunk.get("source_id") or ""),
            "chunk_id": str(chunk.get("chunk_id") or ""),
            "title": str(chunk.get("title") or ""),
            "token_count": int(chunk.get("token_count") or 0),
            "indexed_at": str(chunk.get("indexed_at") or ""),
        },
    )


def search_index(paths: Paths, query: str, *, limit: int = 5) -> list[RetrievedDocument]:
    documents = [_chunk_to_document(chunk) for chunk in db.list_rag_chunks(paths, limit=500)]
    return search_documents(documents, query, limit=limit, sanitize=True)


EMAIL_INDEX_TEXT_CAP = 6000


def index_emails(
    paths: Paths,
    *,
    embedder: Embedder | None = None,
    limit: int = 500,
    indexed_at: str | None = None,
) -> int:
    """Chunk + (optionally) embed every stored email into the RAG store, so the
    assistant can retrieve over mail semantically, not just over imported docs."""
    from sentineldesk.email.ingest import stored_email_messages

    timestamp = indexed_at or utc_now()
    indexed = 0
    for message in stored_email_messages(paths, limit=limit):
        parts = [message.subject, message.body_text, *message.attachment_texts]
        text = "\n\n".join(part for part in parts if part).strip()[:EMAIL_INDEX_TEXT_CAP]
        if not text:
            continue
        metadata = {"subject": message.subject, "sender": message.sender}
        document = RetrievedDocument(
            source_id=message.source_id,
            source_type="email",
            text=text,
            trust_label=message.trust_label,
            warnings=(),
            metadata=metadata,
        )
        index_document(
            paths, document, title=message.subject, metadata=metadata,
            indexed_at=timestamp, embedder=embedder,
        )
        indexed += 1
    return indexed


def semantic_search(
    paths: Paths, query: str, embedder: Embedder, *, limit: int = 5
) -> list[tuple[RetrievedDocument, float]]:
    """Cosine-rank stored chunks against the query embedding."""
    query_vec = embedder.embed(query)
    if not query_vec:
        return []
    scored: list[tuple[float, RetrievedDocument]] = []
    for chunk in db.list_rag_chunks(paths, limit=2000):
        embedding = chunk.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            continue
        score = cosine(query_vec, embedding)
        if score <= 0.0:
            continue
        scored.append((score, _chunk_to_document(chunk)))
    scored.sort(key=lambda item: -item[0])
    return [(document, score) for score, document in scored[:limit]]


def hybrid_search(
    paths: Paths, query: str, embedder: Embedder, *, limit: int = 5
) -> list[RetrievedDocument]:
    """Fuse semantic (embedding) and keyword rankings with reciprocal rank
    fusion. Equal weight is the balance that works across query types: keyword
    carries proper-noun queries ("USCIS"), semantic carries paraphrase and
    cross-language ones ("我的房租账单" -> the English rent email)."""
    semantic = [document for document, _ in semantic_search(paths, query, embedder, limit=limit * 3)]
    keyword = search_index(paths, query, limit=limit * 3)
    return _reciprocal_rank_fusion([(semantic, 1.0), (keyword, 1.0)], limit=limit)


def _reciprocal_rank_fusion(
    weighted_lists: list[tuple[list[RetrievedDocument], float]], *, limit: int, k: int = 60
) -> list[RetrievedDocument]:
    scores: dict[str, float] = {}
    documents: dict[str, RetrievedDocument] = {}
    for ranked, weight in weighted_lists:
        for rank, document in enumerate(ranked):
            key = str(document.metadata.get("chunk_id") or document.source_id)
            scores[key] = scores.get(key, 0.0) + weight / (k + rank)
            documents[key] = document
    ordered = sorted(scores, key=lambda key: -scores[key])
    return [documents[key] for key in ordered[:limit]]


def _chunk_text(text: str, *, source_id: str, chunk_size: int) -> list[tuple[str, str]]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs or [text.strip()]:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = paragraph[:chunk_size]
        remainder = paragraph[chunk_size:]
        while remainder:
            chunks.append(current)
            current = remainder[:chunk_size]
            remainder = remainder[chunk_size:]
    if current:
        chunks.append(current)
    return [(f"{source_id}#chunk-{index}", chunk) for index, chunk in enumerate(chunks)]


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
