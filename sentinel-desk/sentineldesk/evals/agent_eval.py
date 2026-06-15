"""Eval for the LLM-in-the-loop agent paths: intent routing and calendar-event
slot extraction.

Routing has a deterministic keyword layer plus a model fallback, so the harness
can run keyword-only (no model — CI-safe) or keyword+model (needs a chat client).
Slot extraction is entirely model-driven, so it always needs a client and is a
live eval. Both read JSONL golden sets in the same spirit as the email-extract
eval and report per-category accuracy plus the failures.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sentineldesk.extract import utc_now

from ..agent.graph.calendar_action import _extract_slots
from ..agent.router import resolve_intent


def _load_jsonl(path: str | Path) -> list[dict]:
    source = Path(path)
    cases: list[dict] = []
    seen: set[str] = set()
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise ValueError(f"{source.name}:{line_number}: invalid JSON: {error}") from error
        case_id = str(raw.get("case_id") or "")
        if case_id in seen:
            raise ValueError(f"{source.name}:{line_number}: duplicate case_id {case_id}")
        seen.add(case_id)
        cases.append(raw)
    return cases


def _accuracy(correct: int, total: int) -> float | None:
    return None if total == 0 else round(correct / total, 4)


# ---------------------------------------------------------------- routing eval

@dataclass
class RouteCaseResult:
    case_id: str
    category: str
    question: str
    expected: str
    predicted: str
    routed_by: str
    needs_model: bool
    correct: bool


@dataclass
class RouteReport:
    generated_at: str
    golden_path: str
    used_model: bool
    case_count: int
    accuracy: float | None
    keyword_clear_accuracy: float | None          # over needs_model == false cases
    model_dependent_accuracy: float | None        # over needs_model == true cases
    by_category: dict[str, dict] = field(default_factory=dict)
    failures: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_routing(golden_path: str | Path, *, client: Any = None) -> RouteReport:
    cases = _load_jsonl(golden_path)
    results: list[RouteCaseResult] = []
    for case in cases:
        decision = resolve_intent(
            str(case.get("question") or ""),
            previous_intent=case.get("previous_intent"),
            client=client,
        )
        predicted = decision.intent.value
        correct = predicted == str(case.get("expected_intent") or "")
        if correct and case.get("expected_general_mode"):
            correct = decision.general_mode == case.get("expected_general_mode")
        results.append(
            RouteCaseResult(
                case_id=str(case.get("case_id") or ""),
                category=str(case.get("category") or "uncategorized"),
                question=str(case.get("question") or ""),
                expected=str(case.get("expected_intent") or ""),
                predicted=predicted,
                routed_by=decision.routed_by,
                needs_model=bool(case.get("needs_model")),
                correct=correct,
            )
        )

    by_category: dict[str, dict] = {}
    for result in results:
        bucket = by_category.setdefault(result.category, {"count": 0, "correct": 0})
        bucket["count"] += 1
        bucket["correct"] += int(result.correct)
    for bucket in by_category.values():
        bucket["accuracy"] = _accuracy(bucket["correct"], bucket["count"])

    kw = [r for r in results if not r.needs_model]
    md = [r for r in results if r.needs_model]
    return RouteReport(
        generated_at=utc_now(),
        golden_path=str(golden_path),
        used_model=client is not None,
        case_count=len(results),
        accuracy=_accuracy(sum(r.correct for r in results), len(results)),
        keyword_clear_accuracy=_accuracy(sum(r.correct for r in kw), len(kw)),
        model_dependent_accuracy=_accuracy(sum(r.correct for r in md), len(md)),
        by_category=dict(sorted(by_category.items())),
        failures=[
            {"case_id": r.case_id, "question": r.question, "expected": r.expected,
             "predicted": r.predicted, "routed_by": r.routed_by}
            for r in results if not r.correct
        ],
    )


# ---------------------------------------------------------------- slot eval

@dataclass
class SlotReport:
    generated_at: str
    golden_path: str
    case_count: int
    overall_accuracy: float | None          # all expected fields correct (incl. abstention)
    date_accuracy: float | None             # of the cases that should yield a date
    abstention_accuracy: float | None       # of the no-event cases, correctly returned nothing
    by_category: dict[str, dict] = field(default_factory=dict)
    failures: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _slots_match(slots: dict, expected: dict) -> tuple[bool, bool]:
    """Return (all_fields_ok, date_ok). Date is the load-bearing field; title is a
    substring check and times are exact when the golden specifies them."""
    date_ok = slots.get("date") == expected.get("date")
    ok = date_ok
    if "start_time" in expected:
        ok = ok and slots.get("start_time") == expected["start_time"]
    if "end_time" in expected:
        ok = ok and slots.get("end_time") == expected["end_time"]
    if "title_contains" in expected:
        ok = ok and str(expected["title_contains"]).casefold() in str(slots.get("title") or "").casefold()
    return ok, date_ok


def evaluate_slots(golden_path: str | Path, *, client: Any) -> SlotReport:
    cases = _load_jsonl(golden_path)
    rows: list[dict] = []
    for case in cases:
        slots = _extract_slots(str(case.get("question") or ""), client=client, today=str(case.get("today") or ""))
        expected = case.get("expected")
        if expected is None:
            correct = slots is None
            date_ok = None
        else:
            correct, date_ok = _slots_match(slots, expected) if slots is not None else (False, False)
        rows.append({
            "case_id": str(case.get("case_id") or ""),
            "category": str(case.get("category") or "uncategorized"),
            "question": str(case.get("question") or ""),
            "expected": expected,
            "got": slots,
            "correct": correct,
            "date_ok": date_ok,
        })

    by_category: dict[str, dict] = {}
    for row in rows:
        bucket = by_category.setdefault(row["category"], {"count": 0, "correct": 0})
        bucket["count"] += 1
        bucket["correct"] += int(row["correct"])
    for bucket in by_category.values():
        bucket["accuracy"] = _accuracy(bucket["correct"], bucket["count"])

    dated = [r for r in rows if r["expected"] is not None]
    abstain = [r for r in rows if r["expected"] is None]
    return SlotReport(
        generated_at=utc_now(),
        golden_path=str(golden_path),
        case_count=len(rows),
        overall_accuracy=_accuracy(sum(r["correct"] for r in rows), len(rows)),
        date_accuracy=_accuracy(sum(1 for r in dated if r["date_ok"]), len(dated)),
        abstention_accuracy=_accuracy(sum(r["correct"] for r in abstain), len(abstain)),
        by_category=dict(sorted(by_category.items())),
        failures=[
            {"case_id": r["case_id"], "question": r["question"], "expected": r["expected"], "got": r["got"]}
            for r in rows if not r["correct"]
        ],
    )


# ---------------------------------------------------------------- rendering

def render_routing_summary(report: RouteReport) -> str:
    lines = [
        f"Routing eval — {report.case_count} cases (model={'on' if report.used_model else 'off'})",
        f"  overall accuracy:         {report.accuracy}",
        f"  keyword-clear accuracy:   {report.keyword_clear_accuracy}",
        f"  model-dependent accuracy: {report.model_dependent_accuracy}",
        "  by category:",
    ]
    for category, bucket in report.by_category.items():
        lines.append(f"    {category:14s} {bucket['correct']}/{bucket['count']}  acc={bucket['accuracy']}")
    if report.failures:
        lines.append("  failures:")
        for failure in report.failures:
            lines.append(f"    [{failure['case_id']}] {failure['question']!r} -> {failure['predicted']} (want {failure['expected']})")
    return "\n".join(lines)


def render_slots_summary(report: SlotReport) -> str:
    lines = [
        f"Calendar-slot eval — {report.case_count} cases",
        f"  overall accuracy:    {report.overall_accuracy}",
        f"  date accuracy:       {report.date_accuracy}",
        f"  abstention accuracy: {report.abstention_accuracy}",
        "  by category:",
    ]
    for category, bucket in report.by_category.items():
        lines.append(f"    {category:18s} {bucket['correct']}/{bucket['count']}  acc={bucket['accuracy']}")
    if report.failures:
        lines.append("  failures:")
        for failure in report.failures:
            lines.append(f"    [{failure['case_id']}] {failure['question']!r}\n        want={failure['expected']} got={failure['got']}")
    return "\n".join(lines)
