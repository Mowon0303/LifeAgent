"""Cited policy answers from the local RAG index (POLICY_QUESTION intent)."""

from __future__ import annotations

from ..schemas import AgentAnswer, Citation, Intent
from ..tools import ToolRegistry


def _answer_policy_question(active_registry: ToolRegistry, question: str) -> AgentAnswer:
    try:
        spec = active_registry.assert_can_call("search_policy_docs")
    except (KeyError, PermissionError) as error:
        return AgentAnswer(
            intent=Intent.POLICY_QUESTION,
            answer=f"I cannot search local policy documents for this question: {type(error).__name__}: {error}",
            confidence="uncertain",
            tool_calls=("search_policy_docs",),
            uncertain=True,
        )
    if spec.handler is None:
        return AgentAnswer(
            intent=Intent.POLICY_QUESTION,
            answer="I need a configured local RAG index to answer this policy question with citations.",
            confidence="uncertain",
            tool_calls=("search_policy_docs",),
            uncertain=True,
        )
    try:
        result = active_registry.call("search_policy_docs", query=question, limit=3)
    except Exception as error:
        return AgentAnswer(
            intent=Intent.POLICY_QUESTION,
            answer=f"I could not search the local RAG index: {type(error).__name__}: {error}",
            confidence="uncertain",
            tool_calls=("search_policy_docs",),
            uncertain=True,
        )
    documents = list(result.get("documents") or []) if isinstance(result, dict) else []
    if not documents:
        return AgentAnswer(
            intent=Intent.POLICY_QUESTION,
            answer="I could not find a cited local policy document for this question.",
            confidence="uncertain",
            tool_calls=("search_policy_docs",),
            uncertain=True,
        )
    top = documents[0]
    metadata = dict(top.get("metadata") or {})
    title = str(metadata.get("title") or top.get("source_id") or "local policy document")
    warnings = list(top.get("warnings") or [])
    warning_text = " The retrieved text had prompt-injection warnings and was sanitized." if warnings else ""
    answer_text = _short_answer_from_doc(str(top.get("text") or ""))
    citations = tuple(
        Citation(
            source_id=str(document.get("source_id") or ""),
            source_type=str(document.get("source_type") or "local_doc"),
            evidence=str((document.get("metadata") or {}).get("document_source_id") or document.get("source_id") or ""),
            captured_at=str((document.get("metadata") or {}).get("indexed_at") or ""),
        )
        for document in documents
    )
    return AgentAnswer(
        intent=Intent.POLICY_QUESTION,
        answer=f"From {title}: {answer_text}{warning_text}",
        confidence="high" if str(top.get("trust_label") or "") in {"trusted_policy", "trusted_doc", "official_policy"} else "medium",
        citations=citations,
        tool_calls=("search_policy_docs",),
        metadata={
            "document_count": len(documents),
            "top_trust_label": str(top.get("trust_label") or ""),
            "top_score": metadata.get("score"),
            "warnings": warnings,
        },
    )


def _short_answer_from_doc(text: str, *, limit: int = 280) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."
