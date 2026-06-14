"""Conversation memory: a budgeted dialogue context for the router and refiner.

The recent turns ride verbatim; once they exceed a token budget the oldest turns
fold into a deterministic, structured gist — the operational state of the session
(topics touched, dates/amounts discussed) — so a follow-up like "比如呢" / "那笔钱"
still resolves after the window slides.

Safety property worth stating outright: this is context for *following and
phrasing only*. Every turn re-fetches facts from the DB/email and still passes the
invent-guard, so a lossy compaction can blur conversational continuity but can
never inject a wrong number into an answer. That's why the compaction can be cheap
and deterministic instead of an extra (fallible, non-reproducible) model call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sentineldesk.extract import DATE_RE

# Currency- or unit-marked amounts only — a bare number in chit-chat isn't an
# "amount discussed", so we don't surface it in the gist.
_AMOUNT_RE = re.compile(r"[$€£¥￥]\s*\d[\d,]*(?:\.\d{1,2})?|\d[\d,]*(?:\.\d+)?\s*(?:美元|美金|元|块|usd|rmb)", re.IGNORECASE)
_CJK_DATE_RE = re.compile(r"(?:\d{4}\s*年)?\s*\d{1,2}\s*月\s*\d{1,2}\s*[日号]")

# A generous default for a local 7B: ~1800 tokens of history fits roughly a dozen
# short Q&A turns while leaving the bulk of the context window for facts/evidence.
DEFAULT_HISTORY_BUDGET_TOKENS = 1800
_ANSWER_DIGEST_CHARS = 140


@dataclass(frozen=True)
class Turn:
    question: str
    intent: str
    answer: str


@dataclass(frozen=True)
class ConversationMemory:
    summary: str            # rolling compact gist of older turns ("" when none)
    recent: tuple[Turn, ...]  # newest turns, carried verbatim

    def is_empty(self) -> bool:
        return not self.summary and not self.recent

    def as_prompt_block(self) -> str:
        """Render the memory for a model prompt, or "" when there's nothing to add."""
        if self.is_empty():
            return ""
        lines = ["<对话上下文>"]
        if self.summary:
            lines.append(self.summary)
        if self.recent:
            lines.append("最近对话：")
            for turn in self.recent:
                lines.append("用户：" + turn.question)
                digest = _digest(turn.answer)
                if digest:
                    lines.append("助手：" + digest)
        lines.append("</对话上下文>")
        # Reinforce the safety contract to the model: context is for reference only.
        lines.append("（以上仅用于理解接话/指代，事实仍以下方证据为准。）")
        return "\n".join(lines)


def build_memory(
    history: list[dict] | None, *, budget_tokens: int = DEFAULT_HISTORY_BUDGET_TOKENS
) -> ConversationMemory:
    turns = _coerce_turns(history)
    if not turns:
        return ConversationMemory(summary="", recent=())

    # Keep a contiguous suffix of the newest turns under the token budget; the
    # oldest always at least one recent turn survives verbatim.
    used = 0
    split = 0  # turns[:split] -> older (compacted), turns[split:] -> recent
    for idx in range(len(turns) - 1, -1, -1):
        turn = turns[idx]
        cost = _est_tokens(turn.question) + _est_tokens(turn.answer)
        if idx < len(turns) - 1 and used + cost > budget_tokens:
            split = idx + 1
            break
        used += cost
        split = idx

    older = turns[:split]
    recent = turns[split:]
    return ConversationMemory(summary=_compact(older), recent=tuple(recent))


def _coerce_turns(history: list[dict] | None) -> list[Turn]:
    turns: list[Turn] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        turns.append(
            Turn(
                question=question,
                intent=str(item.get("intent") or "").strip(),
                answer=str(item.get("answer") or "").strip(),
            )
        )
    return turns


def _compact(older: list[Turn]) -> str:
    """Fold older turns into a deterministic gist: the topics touched plus the
    load-bearing entities (dates/amounts) so later references still resolve."""
    if not older:
        return ""
    topics = _unique(turn.intent for turn in older if turn.intent)
    entities = _unique(
        match
        for turn in older
        for text in (turn.question, turn.answer)
        for match in _entities(text)
    )
    lines = ["更早聊过（供接话/指代用，非事实来源）："]
    if topics:
        lines.append("- 话题：" + "、".join(topics[:6]))
    if entities:
        lines.append("- 提到的日期/金额：" + "、".join(entities[:8]))
    return "\n".join(lines)


def _entities(text: str) -> list[str]:
    found: list[str] = []
    found.extend(match.group(0).strip() for match in DATE_RE.finditer(text))
    found.extend(match.group(0).strip() for match in _CJK_DATE_RE.finditer(text))
    found.extend(match.group(0).strip() for match in _AMOUNT_RE.finditer(text))
    return found


def _digest(answer: str) -> str:
    text = " ".join(answer.split())
    if len(text) <= _ANSWER_DIGEST_CHARS:
        return text
    return text[:_ANSWER_DIGEST_CHARS].rstrip() + "…"


def _unique(values) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _est_tokens(text: str) -> int:
    """Cheap mixed CJK/ASCII token estimate — a budget, not a billing meter. CJK
    runs ~1.3 tokens/char, Latin ~0.3 (≈ 4 chars/token)."""
    if not text:
        return 0
    cjk = sum(1 for ch in text if ord(ch) >= 0x2E80)  # CJK radicals and beyond
    return int(cjk * 1.3 + (len(text) - cjk) * 0.3) + 1
