"""Open-ended answers: the greeting/capability reply and the email-RAG fallback."""

from __future__ import annotations

from ..llm import grounded_values
from ..router import is_greeting
from ..schemas import AgentAnswer, Citation, Intent
from ..tools import ToolRegistry


def _general_answer(
    question: str, registry: ToolRegistry | None = None, *, general_mode: str | None = None
) -> AgentAnswer:
    """Greetings get the friendly capability reply. An email-content question goes
    to the RAG store. Anything else falls back to the capability guide that lists
    what the agent can do — never a refusal/clarify menu, which on a follow-up reads
    as a bug. (general_mode 'search' is an informational hint from the router.)"""
    greeting = is_greeting(question)
    if not greeting and registry is not None:
        rag = _rag_general_answer(question, registry)
        if rag is not None:
            return rag
    return _capability_reply(greeting)


def _capability_reply(greeting: bool) -> AgentAnswer:
    return AgentAnswer(
        intent=Intent.GENERAL,
        answer=(
            ("你好 👋 " if greeting else "")
            + "我是 LifeAgent 本地日程助手，只读你本地的邮件证据、不外发。"
            "可以帮你查最近的截止日期/待办、待缴金额和账单、解释某个状态或提醒为什么触发、"
            "给下一步建议，或把某条加入日历（确认后才写）。"
            "试着问我「最近有什么截止？」或「这个月要交多少钱？」。"
        ),
        confidence="medium",
        tool_calls=(),
    )


def _rag_general_answer(question: str, registry: ToolRegistry) -> AgentAnswer | None:
    """Retrieve relevant email chunks for an open-ended question, then ground the
    answer in the single most relevant email so the model can't braid one email's
    date onto another. Returns None (fall back to the capability reply) when the
    RAG tool is unavailable or nothing relevant is found."""
    try:
        spec = registry.assert_can_call("search_email_rag")
    except (KeyError, PermissionError):
        return None
    if spec.handler is None:
        return None
    try:
        result = registry.call("search_email_rag", query=question, limit=4)
    except Exception:
        return None
    documents = list(result.get("documents") or []) if isinstance(result, dict) else []
    if not documents:
        return None

    # ③ Single-source focus: the top hit is the primary email. Only its chunks
    # become the model's evidence (citations), so the synthesis can't borrow a date
    # or amount from a different retrieved email.
    primary_id = str(documents[0].get("source_id") or "")
    primary_docs = [d for d in documents if str(d.get("source_id") or "") == primary_id]
    citations = tuple(
        Citation(
            source_id=str(document.get("source_id") or ""),
            source_type=str(document.get("source_type") or "email"),
            evidence=str(document.get("text") or ""),
            captured_at="",
        )
        for document in primary_docs
    )

    # Only the primary email is surfaced as a card — the same single-source the
    # answer is grounded in. Other retrieved emails are counted, not shown, so the
    # answer doesn't trail a wall of loosely-related cards.
    other_sources = {str(d.get("source_id") or "") for d in documents} - {primary_id}
    primary_meta = primary_docs[0].get("metadata") or {}
    primary_title = str(primary_docs[0].get("title") or primary_meta.get("subject") or "这封邮件").strip()
    cards: list[dict] = [
        {
            "kind": "email",
            "title": primary_title,
            "value": "",
            "date": "",
            "source_id": primary_id,
            "sender": str(primary_meta.get("sender") or ""),
            "received": "",
            "evidence": str(primary_docs[0].get("text") or "")[:400],
        }
    ]

    # ② Seed the deterministic base answer with the primary email's real dates /
    # amounts. The free-mode invent guard allows exactly these (plus the primary
    # evidence) — so the model may phrase them naturally but can't add 8/25 from a
    # competition email.
    primary_text = "\n".join(str(d.get("text") or "") for d in primary_docs)
    facts = grounded_values(primary_text)
    summary = "关于「" + primary_title + "」，我在你的邮件里找到相关内容"
    summary += ("：" + "、".join(facts[:6]) + "。" if facts else "。")
    if other_sources:
        summary += "（另有 " + str(len(other_sources)) + " 封相关邮件未展开。）"
    summary += "请以来源邮件为准。"
    return AgentAnswer(
        intent=Intent.GENERAL,
        answer=summary,
        confidence="medium",
        citations=citations,
        tool_calls=("search_email_rag",),
        metadata={"rag": True, "retrieved": len(documents), "primary_source": primary_id, "cards": cards},
    )
