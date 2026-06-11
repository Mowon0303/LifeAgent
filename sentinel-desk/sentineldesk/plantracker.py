from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import project_root


DONE_STATUSES = {"done", "complete", "completed"}


@dataclass(frozen=True)
class PlanItem:
    area: str
    status: str
    evidence: str
    next_work: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def default_plan_path() -> Path:
    return project_root().parent / "PLAN_TRACKER.md"


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_status_table(markdown: str) -> list[PlanItem]:
    items: list[PlanItem] = []
    in_table = False
    for line in markdown.splitlines():
        if line.strip() == "## Status Table":
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if not in_table or not line.startswith("|"):
            continue
        cells = _split_table_row(line)
        if len(cells) < 4 or cells[0] == "Area" or set(cells[0]) == {"-"}:
            continue
        items.append(PlanItem(area=cells[0], status=cells[1], evidence=cells[2], next_work=cells[3]))
    return items


def parse_response_condition(markdown: str) -> dict[str, str]:
    values: dict[str, str] = {}
    in_section = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped == "## Response Condition":
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if not in_section or not stripped.startswith("- "):
            continue
        body = stripped[2:]
        if ":" not in body:
            continue
        key, value = body.split(":", 1)
        values[key.strip().lower()] = value.strip()
    return values


def completed_items(items: list[PlanItem]) -> list[PlanItem]:
    return [item for item in items if item.status.strip().lower() in DONE_STATUSES]


def next_plan(items: list[PlanItem], response_condition: dict[str, str]) -> dict[str, str]:
    explicit = response_condition.get("next plan to complete") or response_condition.get("下一个该完成的计划")
    if explicit:
        return {"area": "Response condition", "work": explicit}
    for item in items:
        if item.status.strip().lower() not in DONE_STATUSES:
            return {"area": item.area, "work": item.next_work}
    if items:
        return {"area": items[0].area, "work": items[0].next_work}
    return {"area": "None", "work": "No tracked plan items found."}


def summarize_plan(plan_path: Path | None = None) -> dict[str, Any]:
    path = plan_path or default_plan_path()
    markdown = path.read_text(encoding="utf-8")
    items = parse_status_table(markdown)
    condition = parse_response_condition(markdown)
    return {
        "plan_path": str(path),
        "reply_condition": condition.get(
            "rule",
            "Every plan-status reply must show completed plans and the next plan to complete.",
        ),
        "completed_plans": [item.to_dict() for item in completed_items(items)],
        "next_plan": next_plan(items, condition),
        "tracked_count": len(items),
        "completed_count": len(completed_items(items)),
    }


def format_plan_summary(summary: dict[str, Any]) -> str:
    lines = [
        "已完成的计划:",
    ]
    completed = summary.get("completed_plans", [])
    if completed:
        for item in completed:
            lines.append(f"- {item['area']}: {item['evidence']}")
    else:
        lines.append("- 暂无")
    next_item = summary.get("next_plan", {})
    lines.extend(
        [
            "",
            "下一个该完成的计划:",
            f"- {next_item.get('area', 'None')}: {next_item.get('work', 'No tracked plan items found.')}",
        ]
    )
    return "\n".join(lines)
