"""Queries for the local RAG store (``rag_documents`` + ``rag_chunks``)."""

from __future__ import annotations

from typing import Any

from ..config import Paths
from .base import _json, decode_rows, open_db


def upsert_rag_document(
    paths: Paths,
    *,
    source_id: str,
    source_type: str,
    trust_label: str,
    title: str,
    metadata: dict[str, Any],
    chunks: list[dict[str, Any]],
    indexed_at: str,
) -> int:
    with open_db(paths) as conn:
        existing = conn.execute("SELECT id FROM rag_documents WHERE source_id = ?", (source_id,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE rag_documents
                SET source_type = ?, trust_label = ?, title = ?, metadata_json = ?, indexed_at = ?
                WHERE source_id = ?
                """,
                (source_type, trust_label, title, _json(metadata), indexed_at, source_id),
            )
            document_id = int(existing["id"])
            conn.execute("DELETE FROM rag_chunks WHERE source_id = ?", (source_id,))
        else:
            cursor = conn.execute(
                """
                INSERT INTO rag_documents(source_id, source_type, trust_label, title, metadata_json, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (source_id, source_type, trust_label, title, _json(metadata), indexed_at),
            )
            document_id = int(cursor.lastrowid)
        for chunk in chunks:
            embedding = chunk.get("embedding")
            conn.execute(
                """
                INSERT INTO rag_chunks(source_id, chunk_id, text, warnings_json, token_count, indexed_at, embedding_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    str(chunk["chunk_id"]),
                    str(chunk["text"]),
                    _json(list(chunk.get("warnings", []))),
                    int(chunk.get("token_count", 0)),
                    indexed_at,
                    _json(list(embedding)) if embedding else "",
                ),
            )
        return document_id


def list_rag_documents(paths: Paths, *, limit: int = 100) -> list[dict[str, Any]]:
    with open_db(paths) as conn:
        rows = conn.execute(
            "SELECT * FROM rag_documents ORDER BY indexed_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return decode_rows(rows)


def embedded_rag_source_ids(paths: Paths) -> set[str]:
    """Source ids that already have at least one embedded chunk — used to embed
    only newly arrived mail instead of re-embedding everything."""
    with open_db(paths) as conn:
        rows = conn.execute(
            "SELECT DISTINCT source_id FROM rag_chunks WHERE embedding_json != ''"
        ).fetchall()
    return {str(row["source_id"]) for row in rows}


def list_rag_chunks(paths: Paths, *, limit: int = 200) -> list[dict[str, Any]]:
    with open_db(paths) as conn:
        rows = conn.execute(
            """
            SELECT c.*, d.source_type, d.trust_label, d.title, d.metadata_json
            FROM rag_chunks c
            JOIN rag_documents d ON d.source_id = c.source_id
            ORDER BY c.indexed_at DESC, c.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return decode_rows(rows)
