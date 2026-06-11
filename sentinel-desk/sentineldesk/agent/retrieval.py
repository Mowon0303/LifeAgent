from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any


INJECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bignore\b.{0,40}\b(previous|prior|system|developer)\b.{0,40}\binstructions?\b", "ignore_instructions"),
    (r"\b(disregard|override)\b.{0,40}\b(system|developer|previous|prior)\b", "override_instructions"),
    (r"\b(system prompt|developer message|hidden instructions?)\b", "prompt_exfiltration"),
    (r"\b(send|forward|email|upload|delete|sync|submit)\b.{0,80}\bwithout (asking|confirmation|permission)\b", "unsafe_tool_instruction"),
    (r"\b(call|invoke|use)\b.{0,40}\btool\b.{0,80}\b(secret|credential|token|password|calendar|email)\b", "unsafe_tool_instruction"),
    (r"\b(exfiltrate|leak|reveal|print)\b.{0,60}\b(secret|credential|token|password|private)\b", "data_exfiltration"),
)


@dataclass(frozen=True)
class RetrievedDocument:
    source_id: str
    source_type: str
    text: str
    trust_label: str = "untrusted"
    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


TRUST_WEIGHTS = {
    "trusted_policy": 2.0,
    "trusted_doc": 1.75,
    "official_policy": 1.75,
    "user_imported": 1.2,
    "email_evidence": 1.1,
    "attachment_evidence": 1.1,
    "portal_verified": 1.1,
    "email_unverified": 0.9,
    "untrusted_web": 0.55,
    "untrusted": 0.45,
}


def detect_prompt_injection(text: str) -> tuple[str, ...]:
    findings: list[str] = []
    for pattern, label in INJECTION_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            findings.append(label)
    return tuple(sorted(set(findings)))


def sanitize_document(document: RetrievedDocument) -> RetrievedDocument:
    warnings = detect_prompt_injection(document.text)
    if not warnings:
        return document
    safe_lines = []
    for line in document.text.splitlines():
        if detect_prompt_injection(line):
            safe_lines.append("[removed untrusted instruction]")
        else:
            safe_lines.append(line)
    return RetrievedDocument(
        source_id=document.source_id,
        source_type=document.source_type,
        text="\n".join(safe_lines),
        trust_label=document.trust_label,
        warnings=tuple(sorted(set(document.warnings + warnings))),
        metadata=dict(document.metadata),
    )


def search_documents(
    documents: list[RetrievedDocument],
    query: str,
    *,
    limit: int = 5,
    sanitize: bool = True,
) -> list[RetrievedDocument]:
    terms = _tokenize(query)
    scored: list[tuple[float, int, RetrievedDocument]] = []
    for index, doc in enumerate(documents):
        candidate = sanitize_document(doc) if sanitize else doc
        score, score_metadata = score_document(candidate, terms, raw_query=query)
        if score > 0:
            scored.append(
                (
                    score,
                    index,
                    replace(
                        candidate,
                        metadata={
                            **candidate.metadata,
                            **score_metadata,
                        },
                    ),
                )
            )
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [doc for _, _, doc in scored[:limit]]


def score_document(document: RetrievedDocument, terms: list[str], *, raw_query: str = "") -> tuple[float, dict[str, Any]]:
    if not terms:
        return 0.0, {}
    text_tokens = Counter(_tokenize(document.text))
    title = str(document.metadata.get("title") or "")
    title_tokens = Counter(_tokenize(title))
    matched_terms = [term for term in terms if text_tokens[term] or title_tokens[term]]
    if not matched_terms:
        return 0.0, {}
    overlap = sum(min(text_tokens[term], 3) for term in matched_terms)
    title_boost = sum(1 for term in matched_terms if title_tokens[term]) * 0.75
    phrase_boost = 1.5 if raw_query and raw_query.lower() in document.text.lower() else 0.0
    trust_weight = TRUST_WEIGHTS.get(document.trust_label, TRUST_WEIGHTS["untrusted"])
    warning_penalty = 0.8 if document.warnings else 1.0
    score = (overlap + title_boost + phrase_boost) * trust_weight * warning_penalty
    return score, {
        "score": round(score, 4),
        "matched_terms": matched_terms,
        "trust_weight": trust_weight,
        "ranking": "sparse_lexical_v1",
    }


def build_retrieval_context(documents: list[RetrievedDocument]) -> str:
    blocks = []
    for doc in documents:
        safe_doc = sanitize_document(doc)
        warning_text = ",".join(safe_doc.warnings) if safe_doc.warnings else "none"
        blocks.append(
            "\n".join(
                [
                    f"[source_id={safe_doc.source_id}]",
                    f"[source_type={safe_doc.source_type}]",
                    f"[trust_label={safe_doc.trust_label}]",
                    f"[warnings={warning_text}]",
                    f"[metadata={safe_doc.metadata}]",
                    safe_doc.text,
                ]
            )
        )
    return "\n\n".join(blocks)


def _tokenize(value: str) -> list[str]:
    return [term.lower() for term in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", value) if term.strip()]
