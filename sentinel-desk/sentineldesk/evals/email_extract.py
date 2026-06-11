"""Golden-set evaluation harness for the email fact extraction layer.

Measures field-level precision/recall/F1 of ``extract_email_facts`` against a
hand-labeled golden set. Labels are semantic ground truth (what a life-admin
assistant should surface), not predictions of current extractor behavior, so
the report exposes real capability gaps instead of confirming the status quo.

Two layers are scored:

- ``raw``: every extracted fact counts.
- ``high_confidence``: only facts at or above ``HIGH_CONFIDENCE_THRESHOLD``,
  which is the same boundary the assistant uses to call an answer "high"
  confidence. High-confidence precision is the number that matters most,
  because downstream calendar drafts and answers rank by confidence.

Matching rules:

- ``deadline``/``amount``: case-insensitive exact match on the extracted value
  string, after collapsing duplicates to unique values per message.
- ``action``: each expected entry is a substring that must appear in at least
  one extracted action (case-insensitive). Extracted actions that cover no
  expected entry count as false positives.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sentineldesk.email.extract import extract_email_facts
from sentineldesk.email.models import EmailMessage
from sentineldesk.extract import utc_now

HIGH_CONFIDENCE_THRESHOLD = 0.75
SET_KINDS = ("deadline", "amount")
ALL_KINDS = ("deadline", "amount", "action")
LAYERS = ("raw", "high_confidence")


@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    category: str
    note: str
    message: EmailMessage
    expected: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class CaseKindResult:
    true_positives: tuple[str, ...]
    false_positives: tuple[str, ...]
    false_negatives: tuple[str, ...]


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    category: str
    note: str
    layers: dict[str, dict[str, CaseKindResult]]


@dataclass
class Tally:
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    def add(self, result: CaseKindResult) -> None:
        self.true_positives += len(result.true_positives)
        self.false_positives += len(result.false_positives)
        self.false_negatives += len(result.false_negatives)

    @property
    def precision(self) -> float | None:
        denominator = self.true_positives + self.false_positives
        if denominator == 0:
            return None
        return self.true_positives / denominator

    @property
    def recall(self) -> float | None:
        denominator = self.true_positives + self.false_negatives
        if denominator == 0:
            return None
        return self.true_positives / denominator

    @property
    def f1(self) -> float | None:
        precision = self.precision
        recall = self.recall
        if precision is None or recall is None or (precision + recall) == 0:
            return None
        return 2 * precision * recall / (precision + recall)

    def to_dict(self) -> dict[str, Any]:
        return {
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }


@dataclass
class EvalReport:
    generated_at: str
    golden_path: str
    case_count: int
    category_counts: dict[str, int] = field(default_factory=dict)
    overall: dict[str, dict[str, Tally]] = field(default_factory=dict)
    by_category: dict[str, dict[str, dict[str, Tally]]] = field(default_factory=dict)
    confidence_buckets: dict[str, dict[str, Tally]] = field(default_factory=dict)
    case_results: list[CaseResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "golden_path": self.golden_path,
            "case_count": self.case_count,
            "category_counts": dict(sorted(self.category_counts.items())),
            "overall": {
                layer: {kind: tally.to_dict() for kind, tally in kinds.items()}
                for layer, kinds in self.overall.items()
            },
            "by_category": {
                category: {
                    layer: {kind: tally.to_dict() for kind, tally in kinds.items()}
                    for layer, kinds in layers.items()
                }
                for category, layers in sorted(self.by_category.items())
            },
            "confidence_buckets": {
                bucket: {kind: tally.to_dict() for kind, tally in kinds.items()}
                for bucket, kinds in self.confidence_buckets.items()
            },
            "failures": [
                {
                    "case_id": result.case_id,
                    "category": result.category,
                    "note": result.note,
                    "false_positives": {
                        kind: list(kind_result.false_positives)
                        for kind, kind_result in result.layers["raw"].items()
                        if kind_result.false_positives
                    },
                    "false_negatives": {
                        kind: list(kind_result.false_negatives)
                        for kind, kind_result in result.layers["raw"].items()
                        if kind_result.false_negatives
                    },
                }
                for result in self.case_results
                if _has_raw_failures(result)
            ],
        }


def _has_raw_failures(result: CaseResult) -> bool:
    return any(
        kind_result.false_positives or kind_result.false_negatives
        for kind_result in result.layers["raw"].values()
    )


def _normalize_value(value: str) -> str:
    return " ".join(value.split()).casefold()


def load_golden_cases(path: str | Path) -> list[GoldenCase]:
    source = Path(path)
    files: list[Path]
    if source.is_dir():
        files = sorted(source.glob("*.jsonl"))
    else:
        files = [source]
    cases: list[GoldenCase] = []
    seen_ids: set[str] = set()
    for file_path in files:
        for line_number, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as error:
                raise ValueError(f"{file_path.name}:{line_number}: invalid JSON: {error}") from error
            case = _case_from_dict(raw, source=f"{file_path.name}:{line_number}")
            if case.case_id in seen_ids:
                raise ValueError(f"{file_path.name}:{line_number}: duplicate case_id {case.case_id}")
            seen_ids.add(case.case_id)
            cases.append(case)
    return cases


def _case_from_dict(raw: dict[str, Any], *, source: str) -> GoldenCase:
    for required in ("case_id", "category", "message", "expected"):
        if required not in raw:
            raise ValueError(f"{source}: missing required field {required}")
    message_raw = raw["message"]
    message = EmailMessage(
        message_id=str(message_raw.get("message_id") or ""),
        thread_id=str(message_raw.get("thread_id") or "default"),
        sender=str(message_raw.get("sender") or ""),
        subject=str(message_raw.get("subject") or ""),
        received_at=str(message_raw.get("received_at") or ""),
        body_text=str(message_raw.get("body_text") or ""),
        attachment_texts=tuple(message_raw.get("attachment_texts") or ()),
        attachment_names=tuple(message_raw.get("attachment_names") or ()),
        source_type="golden_eval",
        trust_label="golden_fixture",
    )
    expected_raw = raw["expected"]
    expected = {
        "deadline": tuple(str(item) for item in expected_raw.get("deadlines") or ()),
        "amount": tuple(str(item) for item in expected_raw.get("amounts") or ()),
        "action": tuple(str(item) for item in expected_raw.get("actions") or ()),
    }
    return GoldenCase(
        case_id=str(raw["case_id"]),
        category=str(raw["category"]),
        note=str(raw.get("note") or ""),
        message=message,
        expected=expected,
    )


def _unique_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = _normalize_value(value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique


def _score_set_kind(expected: tuple[str, ...], predicted: list[str]) -> CaseKindResult:
    expected_keys = {_normalize_value(value): value for value in expected}
    predicted_unique = _unique_values(predicted)
    true_positives: list[str] = []
    false_positives: list[str] = []
    matched_keys: set[str] = set()
    for value in predicted_unique:
        key = _normalize_value(value)
        if key in expected_keys:
            true_positives.append(value)
            matched_keys.add(key)
        else:
            false_positives.append(value)
    false_negatives = [value for key, value in expected_keys.items() if key not in matched_keys]
    return CaseKindResult(
        true_positives=tuple(true_positives),
        false_positives=tuple(false_positives),
        false_negatives=tuple(false_negatives),
    )


def _score_action_kind(expected: tuple[str, ...], predicted: list[str]) -> CaseKindResult:
    predicted_unique = _unique_values(predicted)
    expected_normalized = [(_normalize_value(value), value) for value in expected]
    covered: set[str] = set()
    true_positives: list[str] = []
    false_positives: list[str] = []
    for value in predicted_unique:
        haystack = _normalize_value(value)
        hits = [original for needle, original in expected_normalized if needle and needle in haystack]
        if hits:
            true_positives.append(value)
            covered.update(hits)
        else:
            false_positives.append(value)
    false_negatives = [original for _, original in expected_normalized if original not in covered]
    return CaseKindResult(
        true_positives=tuple(true_positives),
        false_positives=tuple(false_positives),
        false_negatives=tuple(false_negatives),
    )


def evaluate_case(case: GoldenCase) -> tuple[CaseResult, list[tuple[str, float, bool]]]:
    facts = extract_email_facts(case.message)
    predictions: list[tuple[str, float, bool]] = []
    layers: dict[str, dict[str, CaseKindResult]] = {}
    for layer in LAYERS:
        kind_results: dict[str, CaseKindResult] = {}
        for kind in ALL_KINDS:
            values = [
                fact.value
                for fact in facts
                if fact.kind == kind
                and (layer == "raw" or fact.confidence >= HIGH_CONFIDENCE_THRESHOLD)
            ]
            if kind == "action":
                kind_results[kind] = _score_action_kind(case.expected[kind], values)
            else:
                kind_results[kind] = _score_set_kind(case.expected[kind], values)
        layers[layer] = kind_results
    expected_keysets = {
        kind: {_normalize_value(value) for value in case.expected[kind]} for kind in SET_KINDS
    }
    seen_prediction_keys: set[tuple[str, str]] = set()
    for fact in facts:
        if fact.kind not in SET_KINDS:
            continue
        prediction_key = (fact.kind, _normalize_value(fact.value))
        if prediction_key in seen_prediction_keys:
            continue
        seen_prediction_keys.add(prediction_key)
        is_correct = _normalize_value(fact.value) in expected_keysets[fact.kind]
        predictions.append((fact.kind, fact.confidence, is_correct))
    return (
        CaseResult(case_id=case.case_id, category=case.category, note=case.note, layers=layers),
        predictions,
    )


def evaluate_golden_path(path: str | Path) -> EvalReport:
    cases = load_golden_cases(path)
    report = EvalReport(
        generated_at=utc_now(),
        golden_path=str(path),
        case_count=len(cases),
    )
    report.overall = {layer: {kind: Tally() for kind in ALL_KINDS} for layer in LAYERS}
    report.confidence_buckets = {
        bucket: {kind: Tally() for kind in SET_KINDS} for bucket in ("high", "low")
    }
    for case in cases:
        report.category_counts[case.category] = report.category_counts.get(case.category, 0) + 1
        case_result, predictions = evaluate_case(case)
        report.case_results.append(case_result)
        category_layers = report.by_category.setdefault(
            case.category, {layer: {kind: Tally() for kind in ALL_KINDS} for layer in LAYERS}
        )
        for layer in LAYERS:
            for kind in ALL_KINDS:
                kind_result = case_result.layers[layer][kind]
                report.overall[layer][kind].add(kind_result)
                category_layers[layer][kind].add(kind_result)
        for kind, confidence, is_correct in predictions:
            bucket = "high" if confidence >= HIGH_CONFIDENCE_THRESHOLD else "low"
            tally = report.confidence_buckets[bucket][kind]
            if is_correct:
                tally.true_positives += 1
            else:
                tally.false_positives += 1
    return report


def _format_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def _metrics_row(label: str, tally: Tally) -> str:
    return (
        f"| {label} | {tally.true_positives} | {tally.false_positives} | {tally.false_negatives} "
        f"| {_format_ratio(tally.precision)} | {_format_ratio(tally.recall)} | {_format_ratio(tally.f1)} |"
    )


def render_text_summary(report: EvalReport) -> str:
    lines = [
        f"golden cases: {report.case_count} ({len(report.category_counts)} categories)",
        f"generated at: {report.generated_at}",
    ]
    for layer in LAYERS:
        for kind in ALL_KINDS:
            tally = report.overall[layer][kind]
            lines.append(
                f"{layer}.{kind}: P={_format_ratio(tally.precision)} "
                f"R={_format_ratio(tally.recall)} F1={_format_ratio(tally.f1)} "
                f"(tp={tally.true_positives} fp={tally.false_positives} fn={tally.false_negatives})"
            )
    return "\n".join(lines)


def render_markdown_report(report: EvalReport) -> str:
    lines: list[str] = []
    lines.append("# Email Extraction Eval Report")
    lines.append("")
    lines.append(f"- Generated at: {report.generated_at}")
    lines.append(f"- Golden set: `{report.golden_path}` ({report.case_count} cases)")
    lines.append("- Target under test: `sentineldesk.email.extract.extract_email_facts`")
    lines.append(
        f"- High-confidence threshold: {HIGH_CONFIDENCE_THRESHOLD} "
        "(same boundary the assistant uses for `high` confidence answers)"
    )
    lines.append(
        "- Labels are semantic ground truth for a life-admin assistant; expanded date forms, "
        "relative deadlines, non-dollar currencies, spelled-out dollar amounts, and expanded "
        "action verbs stay labeled even when extractor support is partial, so recall reflects "
        "true capability."
    )
    lines.append("")
    lines.append("## Golden Set Composition")
    lines.append("")
    lines.append("| Category | Cases |")
    lines.append("| --- | --- |")
    for category, count in sorted(report.category_counts.items()):
        lines.append(f"| {category} | {count} |")
    lines.append("")
    lines.append("## Overall Metrics")
    lines.append("")
    for layer, title in (("raw", "Raw layer (every extracted fact)"), ("high_confidence", "High-confidence layer (confidence >= 0.75)")):
        lines.append(f"### {title}")
        lines.append("")
        lines.append("| Kind | TP | FP | FN | Precision | Recall | F1 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for kind in ALL_KINDS:
            lines.append(_metrics_row(kind, report.overall[layer][kind]))
        lines.append("")
    lines.append(
        "Note: action facts carry a fixed confidence of 0.68, so the high-confidence layer "
        "contains no action predictions by construction."
    )
    lines.append("")
    lines.append("## Confidence Calibration (deadline/amount)")
    lines.append("")
    lines.append(
        "Precision per confidence bucket. If the risk-word heuristic works, the high bucket "
        "should not be less precise than the low bucket."
    )
    lines.append("")
    lines.append("| Kind | High bucket precision (n) | Low bucket precision (n) |")
    lines.append("| --- | --- | --- |")
    for kind in SET_KINDS:
        high = report.confidence_buckets["high"][kind]
        low = report.confidence_buckets["low"][kind]
        high_n = high.true_positives + high.false_positives
        low_n = low.true_positives + low.false_positives
        lines.append(
            f"| {kind} | {_format_ratio(high.precision)} ({high_n}) | {_format_ratio(low.precision)} ({low_n}) |"
        )
    lines.append("")
    lines.append("## Per-Category Metrics (raw layer)")
    lines.append("")
    lines.append("| Category | Deadline P/R | Amount P/R | Action P/R |")
    lines.append("| --- | --- | --- | --- |")
    for category in sorted(report.by_category):
        kinds = report.by_category[category]["raw"]
        cells = []
        for kind in ALL_KINDS:
            tally = kinds[kind]
            cells.append(f"{_format_ratio(tally.precision)} / {_format_ratio(tally.recall)}")
        lines.append(f"| {category} | {cells[0]} | {cells[1]} | {cells[2]} |")
    lines.append("")
    lines.append("## Failure Detail (raw layer)")
    lines.append("")
    lines.append("Every case with at least one false positive or false negative.")
    lines.append("")
    lines.append("| Case | Kind | False positives | False negatives |")
    lines.append("| --- | --- | --- | --- |")
    for result in report.case_results:
        if not _has_raw_failures(result):
            continue
        for kind in ALL_KINDS:
            kind_result = result.layers["raw"][kind]
            if not kind_result.false_positives and not kind_result.false_negatives:
                continue
            fp_text = "; ".join(_truncate(value) for value in kind_result.false_positives) or "-"
            fn_text = "; ".join(_truncate(value) for value in kind_result.false_negatives) or "-"
            lines.append(f"| {result.case_id} | {kind} | {fp_text} | {fn_text} |")
    lines.append("")
    lines.append("## Reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append("cd sentinel-desk")
    lines.append("python3 -B -m sentineldesk eval email-extract --golden evals/golden --report-md docs/EVAL_REPORT.md")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _truncate(value: str, limit: int = 60) -> str:
    cleaned = " ".join(value.split())
    cleaned = cleaned.replace("|", "\\|")
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."
