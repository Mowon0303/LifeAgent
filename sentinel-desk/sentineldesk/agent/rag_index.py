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
) -> IndexedDocument:
    db.init_db(paths)
    timestamp = indexed_at or utc_now()
    safe_document = sanitize_document(document)
    chunks = _chunk_text(safe_document.text, source_id=safe_document.source_id, chunk_size=chunk_size)
    db.upsert_rag_document(
        paths,
        source_id=safe_document.source_id,
        source_type=safe_document.source_type,
        trust_label=safe_document.trust_label,
        title=title or safe_document.source_id,
        metadata=metadata or {},
        chunks=[
            {
                "chunk_id": chunk_id,
                "text": text,
                "warnings": safe_document.warnings,
                "token_count": len(text.split()),
            }
            for chunk_id, text in chunks
        ],
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


def search_index(paths: Paths, query: str, *, limit: int = 5) -> list[RetrievedDocument]:
    chunks = db.list_rag_chunks(paths, limit=500)
    documents = [
        RetrievedDocument(
            source_id=str(chunk["chunk_id"]),
            source_type=str(chunk["source_type"]),
            text=str(chunk["text"]),
            trust_label=str(chunk["trust_label"]),
            warnings=tuple(chunk.get("warnings", [])),
            metadata={
                **dict(chunk.get("metadata") or {}),
                "document_source_id": str(chunk.get("source_id") or ""),
                "chunk_id": str(chunk.get("chunk_id") or ""),
                "title": str(chunk.get("title") or ""),
                "token_count": int(chunk.get("token_count") or 0),
                "indexed_at": str(chunk.get("indexed_at") or ""),
            },
        )
        for chunk in chunks
    ]
    return search_documents(documents, query, limit=limit, sanitize=True)


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
