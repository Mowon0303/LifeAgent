from __future__ import annotations

import re
import urllib.error
from dataclasses import dataclass
from typing import Any

from .schemas import Intent


GREETING_TERMS = (
    "你好", "您好", "哈喽", "嗨", "在吗", "在么", "你是谁", "hi", "hello", "hey", "谢谢", "thank",
)


def is_greeting(question: str) -> bool:
    text = question.strip().lower()
    return any(term in text for term in GREETING_TERMS)


FOLLOWUP_TERMS = (
    "其他的呢", "其他呢", "其它的呢", "其它呢", "别的呢", "还有呢", "还有吗", "还有别的",
    "更多", "继续", "接着", "more", "what else", "anything else", "the rest", "go on",
)

# An explicit "list them all" — the user wants the full set, not the single most
# relevant item the overview surfaces by default.
LIST_ALL_TERMS = (
    "全部列出", "全都列出", "都列出", "列出全部", "列出来", "全列出", "全部显示", "都显示",
    "全部都", "list all", "show all", "list them all", "show them all", "list everything",
)


def is_followup(question: str) -> bool:
    """A short 'and the others?' style continuation that only makes sense against
    the previous turn."""
    text = question.strip().lower()
    return len(text) <= 16 and any(term in text for term in FOLLOWUP_TERMS)


def is_list_all(question: str) -> bool:
    """A short 'list them all' request — expands the overview to every item."""
    text = question.strip().lower()
    return len(text) <= 20 and any(term in text for term in LIST_ALL_TERMS)


def _continue_intent(previous_intent: str) -> Intent | None:
    if previous_intent in {"latest_deadline", "latest_amount", "task_overview"}:
        return Intent.TASK_OVERVIEW
    return None


def classify_intent(question: str, *, previous_intent: str | None = None) -> Intent:
    if previous_intent and (is_followup(question) or is_list_all(question)):
        followed = _continue_intent(previous_intent)
        if followed is not None:
            return followed
    text = question.lower()
    if _has_any(text, ["calendar", "日历", "提醒", "remind", "schedule this", "put this"]):
        return Intent.CALENDAR_ACTION
    if _has_any(text, ["next step", "what should i do", "what do i do", "what now", "下一步", "怎么办", "该怎么做"]):
        return Intent.NEXT_STEP_RECOMMENDATION
    if _has_any(text, ["status mean", "what does this status", "状态是什么意思", "状态代表", "status meaning"]):
        return Intent.STATUS_MEANING
    if _has_any(text, ["policy", "rule", "规则", "条款", "什么意思", "mean"]):
        return Intent.POLICY_QUESTION
    if _has_any(text, ["deadline", "due date", "最晚", "截止", "到期", "什么时候"]):
        return Intent.LATEST_DEADLINE
    if _has_any(text, ["balance", "amount", "bill", "invoice", "rent", "how much", "due", "owed", "多少钱", "金额", "欠费", "账单"]):
        return Intent.LATEST_AMOUNT
    if _has_any(text, ["why", "alert", "报警", "为什么", "触发"]):
        return Intent.ALERT_EXPLANATION
    if _has_any(text, ["page change", "页面变化", "网页变化", "changed"]):
        return Intent.PAGE_CHANGE
    # Checked last (after the specific intents) so "最近有什么截止/账单" still route
    # to deadline/amount; only a broad "what's on my plate" lands here.
    if _has_any(text, [
        "重要的事", "要处理", "待办", "要做", "有什么事", "有什么要", "最近有什么", "近期安排",
        "on my plate", "to handle", "to-do", "todo", "to do", "what should i do this",
        "what do i have", "what's due", "overview", "summary",
    ]):
        return Intent.TASK_OVERVIEW
    # a standalone "list them all" defaults to the upcoming-deadline overview
    if is_list_all(question):
        return Intent.TASK_OVERVIEW
    return Intent.GENERAL


def _has_any(text: str, terms: list[str]) -> bool:
    return any(re.search(re.escape(term), text) for term in terms)


# ---- LLM intent fallback: only consulted when the keyword pass yields GENERAL ----
# The keyword router stays the fast, deterministic, zero-dependency default; the
# model generalizes to phrasings/languages/synonyms the keyword lists never cover.
_LLM_LABEL_INTENT = {
    "deadline": Intent.LATEST_DEADLINE,
    "amount": Intent.LATEST_AMOUNT,
    "overview": Intent.TASK_OVERVIEW,
    "calendar": Intent.CALENDAR_ACTION,
    "next_step": Intent.NEXT_STEP_RECOMMENDATION,
    "status": Intent.STATUS_MEANING,
    "policy": Intent.POLICY_QUESTION,
}
# checked in order; "search" => RAG over mail, "unclear" => honest clarify menu
_LLM_LABELS = (*_LLM_LABEL_INTENT.keys(), "search", "unclear")
_LLM_ROUTE_SYSTEM = (
    "You route a personal email/calendar assistant. Output EXACTLY one label, nothing else:\n"
    "deadline = asking about due dates / the nearest deadline\n"
    "amount = how much is owed, a bill, a payment amount\n"
    "overview = what's on my plate / list what needs handling / list all upcoming\n"
    "calendar = add something to the calendar or set a reminder\n"
    "next_step = what should I do next\n"
    "status = what a status or label means\n"
    "policy = what a rule or term means\n"
    "search = looking for the content of a specific email\n"
    "unclear = a greeting, small talk, or it fits none of the above\n"
    "Output only the single label."
)


@dataclass(frozen=True)
class RouteDecision:
    intent: Intent
    routed_by: str  # "keyword" | "llm" | "continue"
    general_mode: str | None = None


def resolve_intent(
    question: str,
    *,
    previous_intent: str | None = None,
    client: Any = None,
    context: str = "",
) -> RouteDecision:
    """The full routing decision, shared by the workflow and the routing eval so
    both exercise the same logic. Keyword pass first; only a GENERAL non-greeting
    consults the model, then falls back to continuing a task thread."""
    intent = classify_intent(question, previous_intent=previous_intent)
    if intent != Intent.GENERAL or is_greeting(question):
        return RouteDecision(intent, "keyword")
    label = llm_route_label(question, client=client, previous_intent=previous_intent, context=context)
    if label in _LLM_LABEL_INTENT:
        return RouteDecision(_LLM_LABEL_INTENT[label], "llm")
    if label == "search":
        return RouteDecision(Intent.GENERAL, "llm", "search")
    continued = _continue_intent(previous_intent or "")
    if continued is not None:
        return RouteDecision(continued, "continue")
    return RouteDecision(Intent.GENERAL, "keyword")


def llm_route_label(
    question: str, *, client: Any, previous_intent: str | None = None, context: str = ""
) -> str | None:
    """Ask the model for one routing label. Returns None when no model is available
    or the call fails, so the caller falls back to the deterministic GENERAL path.

    ``context`` is the rendered conversation memory — it lets the model place a
    follow-up like "比如呢" against what was just discussed instead of guessing."""
    if client is None:
        return None
    user = question.strip()
    if previous_intent:
        user = "Previous turn intent: " + previous_intent + "\nUser message: " + user
    if context:
        user = context + "\n\n" + user
    try:
        result = client.chat(system=_LLM_ROUTE_SYSTEM, user=user)
    except (urllib.error.URLError, OSError, ValueError, KeyError, AttributeError):
        return None
    text = str(getattr(result, "text", "") or "").strip().lower().replace(" ", "_").replace("-", "_")
    for label in _LLM_LABELS:
        if label in text:
            return label
    return None
