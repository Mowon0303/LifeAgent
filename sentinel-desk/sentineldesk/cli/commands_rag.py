"""RAG store commands: index a doc, search, embed emails, list docs."""

from __future__ import annotations

import argparse

from .. import db
from ..agent.embeddings import embedder_for
from ..agent.model import load_model_provider
from ..agent.rag_index import hybrid_search, index_emails, index_file, search_index, semantic_search
from ..config import ensure_dirs
from .common import paths_from_args, print_json


def parse_metadata_pairs(pairs: list[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"metadata must be key=value: {pair}")
        key, value = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"metadata key cannot be empty: {pair}")
        metadata[key] = value.strip()
    return metadata


def cmd_rag_index(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    indexed = index_file(
        paths,
        args.file,
        source_id=args.source_id,
        source_type=args.source_type,
        trust_label=args.trust_label,
        title=args.title,
        metadata=parse_metadata_pairs(args.metadata or []),
    )
    print_json(indexed.__dict__)
    return 0


def cmd_rag_search(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    db.init_db(paths)
    mode = getattr(args, "mode", "keyword")
    if mode in {"semantic", "hybrid"}:
        embedder = embedder_for(load_model_provider(paths))
        if mode == "semantic":
            results = [document for document, _ in semantic_search(paths, args.query, embedder, limit=args.limit)]
        else:
            results = hybrid_search(paths, args.query, embedder, limit=args.limit)
    else:
        results = search_index(paths, args.query, limit=args.limit)
    print_json([result.__dict__ for result in results])
    return 0


def cmd_rag_embed_emails(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    ensure_dirs(paths)
    embedder = embedder_for(load_model_provider(paths))
    count = index_emails(paths, embedder=embedder, limit=args.limit, skip_indexed=not args.all)
    print_json({"emails_indexed": count, "embedder": embedder.name, "mode": "all" if args.all else "new-only"})
    return 0


def cmd_rag_docs(args: argparse.Namespace) -> int:
    paths = paths_from_args(args)
    db.init_db(paths)
    print_json(db.list_rag_documents(paths, limit=args.limit))
    return 0
