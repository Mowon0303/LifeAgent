from __future__ import annotations

import re

from .schemas import Intent


def classify_intent(question: str) -> Intent:
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
    return Intent.GENERAL


def _has_any(text: str, terms: list[str]) -> bool:
    return any(re.search(re.escape(term), text) for term in terms)
