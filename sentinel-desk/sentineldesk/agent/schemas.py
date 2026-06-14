from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Intent(str, Enum):
    LATEST_DEADLINE = "latest_deadline"
    LATEST_AMOUNT = "latest_amount"
    TASK_OVERVIEW = "task_overview"
    ALERT_EXPLANATION = "alert_explanation"
    STATUS_MEANING = "status_meaning"
    NEXT_STEP_RECOMMENDATION = "next_step_recommendation"
    CALENDAR_ACTION = "calendar_action"
    PAGE_CHANGE = "page_change"
    POLICY_QUESTION = "policy_question"
    GENERAL = "general"


@dataclass(frozen=True)
class Citation:
    source_id: str
    source_type: str
    evidence: str = ""
    captured_at: str = ""


@dataclass(frozen=True)
class AgentAnswer:
    intent: Intent
    answer: str
    confidence: str
    citations: tuple[Citation, ...] = ()
    tool_calls: tuple[str, ...] = ()
    requires_confirmation: bool = False
    uncertain: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
