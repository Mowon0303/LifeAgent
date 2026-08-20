"""P3 daily product validation: one repeatable pass over the real queue.

P3 asks whether LifeAgent is worth using daily. That question needs several
consecutive days, which means each day has to be cheap to run and directly
comparable to the last -- otherwise the answer degrades into an impression.

Two outputs, deliberately separated:

* ``day-NN.sheet.md``  -- the working sheet. Carries truncated subjects and
  evidence snippets, because judging a false positive without seeing the item
  is not judging. **Stays on this machine.**
* ``day-NN.anon.json`` -- counts, sender *domains*, bands, and probe results.
  No subjects, no addresses, no bodies. This is the file the eventual P3
  summary is written from, so the summary can be published without carrying
  anyone's mail into the repo.

Both land under ``$SENTINEL_HOME/p3/``, never inside the working tree.

What this script decides on its own is only what a machine can actually know:
counts, duplicates, evidence completeness, day-over-day carry-over, and how the
assistant answered a fixed set of probes. Whether a task was *worth surfacing*
is a human call, so the sheet proposes a verdict per item and leaves the column
editable rather than scoring itself.

No external network access: the mailbox is read from local storage. Refreshing
mail from Gmail is a separate, explicitly authorized step.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentineldesk import db  # noqa: E402
from sentineldesk.clock import today_iso, utc_now  # noqa: E402
from sentineldesk.config import get_paths  # noqa: E402
from sentineldesk.daily import build_daily_landing_summary  # noqa: E402
from sentineldesk.tasks import list_tasks  # noqa: E402


# Fixed wording, run identically every day, so a change in the answer means the
# product changed rather than the question did. Mixed Chinese/English on purpose:
# the user asks in Chinese, and an English answer to a Chinese question is itself
# a finding worth catching.
PROBES = (
    "我有哪些待办？",
    "最近有什么截止？",
    "这个月要交多少钱？",
    "我最近有哪些要付的钱？",
    "我欠了多少钱？",
)

_ADDRESS_RE = re.compile(r"<([^>]+)>")
_CJK_RE = re.compile(r"[一-鿿]")


def sender_domain(sender: str) -> str:
    """Sender identity reduced to the part that is not personal."""
    match = _ADDRESS_RE.search(sender or "")
    address = (match.group(1) if match else (sender or "")).strip().lower()
    return address.rsplit("@", 1)[-1] if "@" in address else ""


def _norm(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def collect_tasks(paths) -> list[dict[str, Any]]:
    return list_tasks(paths, limit=1000, sort="priority")


def duplicate_groups(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Same value, same sending domain, different source message.

    This is the mechanical half of "重复项" -- it cannot see that two rent
    reminders are genuinely two events, which is exactly why the sheet asks a
    human to confirm each group rather than reporting a number and moving on.
    """
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for task in tasks:
        key = (sender_domain(str(task.get("sender") or "")), _norm(task.get("value"))[:80])
        if not key[0] or not key[1]:
            continue
        buckets.setdefault(key, []).append(task)
    groups = []
    for (domain, value), items in buckets.items():
        sources = {str(item.get("primary_source") or "") for item in items}
        if len(sources) > 1:
            groups.append(
                {
                    "domain": domain,
                    "value_prefix": value[:60],
                    "task_count": len(items),
                    "source_count": len(sources),
                    "flagged_boilerplate": sum(1 for i in items if i.get("boilerplate")),
                }
            )
    return sorted(groups, key=lambda g: -g["task_count"])


def evidence_completeness(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """A mechanical floor under "evidence drill-down 是否足够".

    It can only check that the parts needed to drill down are *present* -- a
    quoted snippet, a source reference, a timestamp. Whether the snippet
    actually explains the item is the human column in the sheet.
    """
    total = len(tasks)
    if not total:
        return {"total": 0}
    has_evidence = sum(1 for t in tasks if str(t.get("evidence") or "").strip())
    has_source = sum(1 for t in tasks if t.get("source_refs") or t.get("primary_source"))
    has_time = sum(1 for t in tasks if str(t.get("received_at") or "").strip())
    complete = sum(
        1
        for t in tasks
        if str(t.get("evidence") or "").strip()
        and (t.get("source_refs") or t.get("primary_source"))
        and str(t.get("received_at") or "").strip()
    )
    short_evidence = sum(1 for t in tasks if 0 < len(str(t.get("evidence") or "").strip()) < 40)
    return {
        "total": total,
        "with_evidence": has_evidence,
        "with_source_ref": has_source,
        "with_timestamp": has_time,
        "drill_down_complete": complete,
        "evidence_under_40_chars": short_evidence,
    }


def run_probes(paths) -> list[dict[str, Any]]:
    """Ask the assistant the same questions every day and record how it answered.

    Records intent, confidence, whether it flagged uncertainty, how many
    citations it produced, and whether a Chinese question got a Chinese answer.
    The answer text is kept: it is the assistant's own words, not mail content.
    """
    # Same entry point the `sentineldesk ask` command uses, so the probe records
    # what the user would actually get rather than what a lower layer returns.
    from sentineldesk.agent.tools import default_tool_registry
    from sentineldesk.agent.workflow import answer_with_workflow
    from sentineldesk.email.ingest import stored_email_messages
    from sentineldesk.agent.model import load_model_provider

    messages = stored_email_messages(paths)
    results = []
    for question in PROBES:
        try:
            answer = answer_with_workflow(
                question,
                provider=load_model_provider(paths),
                messages=messages,
                registry=default_tool_registry(paths),
                paths=paths,
            )
        except Exception as exc:  # a crashed probe is itself a day-1 finding
            results.append({"question": question, "error": f"{type(exc).__name__}: {exc}"})
            continue
        text = str(answer.answer or "")
        results.append(
            {
                "question": question,
                "intent": answer.intent.value,
                "confidence": str(answer.confidence or ""),
                "uncertain": bool(answer.uncertain),
                "citation_count": len(answer.citations or ()),
                "answered_in_chinese": bool(_CJK_RE.search(text)),
                "answer": " ".join(text.split())[:400],
            }
        )
    return results


def build_snapshot(paths, *, day: int) -> dict[str, Any]:
    tasks = collect_tasks(paths)
    messages = db.list_email_messages(paths, limit=1000)
    facts = db.list_email_facts(paths, limit=2000)
    summary = build_daily_landing_summary(paths, record_audit=False)
    calendar = summary.get("calendar") or {}
    calendar_items = calendar.get("items") or []

    return {
        "day": day,
        "generated_at": utc_now(),
        "product_clock": today_iso(),
        "external_network": False,
        "external_writes_performed": False,
        "counts": {
            "messages_stored": len(messages),
            "facts": dict(Counter(str(f.get("kind") or "?") for f in facts)),
            "tasks_total": len(tasks),
            "tasks_by_kind": dict(Counter(str(t.get("kind") or "?") for t in tasks)),
            "tasks_by_band": dict(Counter(str(t.get("priority_band") or "?") for t in tasks)),
            "tasks_by_status": dict(Counter(str(t.get("status") or "new") for t in tasks)),
            "needs_verification": sum(1 for t in tasks if t.get("needs_verification")),
            "flagged_boilerplate": sum(1 for t in tasks if t.get("boilerplate")),
            "muted": sum(1 for t in tasks if t.get("muted")),
            "calendar_items": len(calendar_items),
            "calendar_approved": sum(1 for c in calendar_items if c.get("approval_state") == "approved"),
        },
        "duplicates": duplicate_groups(tasks),
        "evidence": evidence_completeness(tasks),
        "probes": run_probes(paths),
        # Domain + band only. The ordering is the thing under test; the subject
        # line is not needed to compare two days and is not anonymous.
        "ranking": [
            {
                "rank": i,
                "task_id": str(t.get("task_id") or ""),
                "kind": str(t.get("kind") or ""),
                "band": str(t.get("priority_band") or ""),
                "score": t.get("priority_score"),
                "domain": sender_domain(str(t.get("sender") or "")),
                "settlement": str(t.get("settlement") or ""),
                "reasons": list(t.get("priority_reasons") or []),
            }
            for i, t in enumerate(tasks, 1)
        ],
        # Filled in by the human, in the sheet, and merged back on the next run.
        "human": {
            "valid_tasks": None,
            "false_positives": None,
            "missed_tasks": None,
            "duplicates_confirmed": None,
            "completed_tasks": None,
            "review_minutes": None,
            "time_saved_minutes": None,
            "evidence_sufficient": None,
            "ranking_sensible": None,
            "citations_trustworthy": None,
            "notes": "",
        },
    }


def carry_over(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """New vs carried vs gone.

    A queue that shows the same items every morning is not a daily workflow, so
    this is one of the load-bearing P3 numbers rather than a nicety.
    """
    if not previous:
        return {"comparable": False}
    before = {r["task_id"] for r in previous.get("ranking", [])}
    now = {r["task_id"] for r in current.get("ranking", [])}
    return {
        "comparable": True,
        "previous_day": previous.get("day"),
        "new_today": len(now - before),
        "carried_over": len(now & before),
        "gone_today": len(before - now),
    }


def _sheet(paths, snapshot: dict[str, Any], tasks: list[dict[str, Any]], top: int) -> str:
    counts = snapshot["counts"]
    lines = [
        f"# P3 Day {snapshot['day']} — {snapshot['product_clock']}",
        "",
        "> 本地文件，不要提交。判断列留空的请自己填；机器能算的已经填好了。",
        "",
        "## 机器已知",
        "",
        f"- 邮件 {counts['messages_stored']} 封 · 事实 {counts['facts']}",
        f"- 任务 {counts['tasks_total']}（{counts['tasks_by_kind']}）",
        f"- 优先级分档 {counts['tasks_by_band']}",
        f"- 需要验证 {counts['needs_verification']} · 样板降权 {counts['flagged_boilerplate']} · 静音 {counts['muted']}",
        f"- 日历 {counts['calendar_items']} 条（已确认 {counts['calendar_approved']}）",
    ]
    carry = snapshot.get("carry_over") or {}
    if carry.get("comparable"):
        lines.append(
            f"- 与 Day {carry['previous_day']} 相比：新增 {carry['new_today']} · "
            f"沿用 {carry['carried_over']} · 消失 {carry['gone_today']}"
        )
    ev = snapshot["evidence"]
    if ev.get("total"):
        lines += [
            "",
            f"- Evidence 齐全（摘录+来源+时间）{ev['drill_down_complete']}/{ev['total']}"
            f"，摘录短于 40 字符 {ev['evidence_under_40_chars']}",
        ]

    dups = snapshot["duplicates"]
    lines += ["", "## 疑似重复（同域 + 同内容 + 不同邮件）", ""]
    if dups:
        lines.append("| 发件域 | 内容前缀 | 任务数 | 源邮件数 | 已降权 | 真重复? |")
        lines.append("|---|---|---|---|---|---|")
        for g in dups:
            lines.append(
                f"| {g['domain']} | {g['value_prefix']} | {g['task_count']} | "
                f"{g['source_count']} | {g['flagged_boilerplate']} |  |"
            )
    else:
        lines.append("（无）")

    lines += ["", f"## 排序前 {top} 项 — 逐条判断", ""]
    lines.append("| # | 档 | 分 | 类型 | 发件域 | 标题 | 有效? | 说明 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for i, task in enumerate(tasks[:top], 1):
        title = " ".join(str(task.get("title") or "").split())[:52].replace("|", "/")
        lines.append(
            f"| {i} | {task.get('priority_band','')} | {task.get('priority_score','')} | "
            f"{task.get('kind','')} | {sender_domain(str(task.get('sender') or ''))} | "
            f"{title} |  |  |"
        )

    lines += ["", "### 证据摘录（判断上表用）", ""]
    for i, task in enumerate(tasks[:top], 1):
        snippet = " ".join(str(task.get("evidence") or "").split())[:180]
        lines.append(f"{i}. {snippet or '（无摘录）'}")

    lines += ["", "## 助手探针", ""]
    lines.append("| 问题 | intent | 置信 | 不确定 | 引用数 | 中文回答 |")
    lines.append("|---|---|---|---|---|---|")
    for p in snapshot["probes"]:
        if p.get("error"):
            lines.append(f"| {p['question']} | ERROR | | | | {p['error']} |")
            continue
        lines.append(
            f"| {p['question']} | {p['intent']} | {p['confidence']} | "
            f"{'是' if p['uncertain'] else '否'} | {p['citation_count']} | "
            f"{'是' if p['answered_in_chinese'] else '**否**'} |"
        )
    lines += [""]
    for p in snapshot["probes"]:
        if not p.get("error"):
            lines.append(f"- **{p['question']}** → {p['answer']}")

    lines += [
        "",
        "## 需要你填",
        "",
        "| 项 | 值 |",
        "|---|---|",
        "| 有效任务数 |  |",
        "| 误报数 |  |",
        "| 漏报数（今天真有、系统没抓到的） |  |",
        "| 确认为重复的组数 |  |",
        "| 实际完成的任务数 |  |",
        "| 本次 review 耗时（分钟） |  |",
        "| 主观节省时间（分钟） |  |",
        "| Evidence 够不够判断（够/勉强/不够） |  |",
        "| 排序合不合理（合理/凑合/不合理） |  |",
        "| 引用与不确定性可不可信（可信/存疑/不可信） |  |",
        "",
        "备注：",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one P3 daily validation pass.")
    parser.add_argument("--home", help="SENTINEL_HOME to read (defaults to the env var)")
    parser.add_argument("--day", type=int, help="Day number; defaults to the next unused one")
    parser.add_argument("--top", type=int, default=12, help="How many ranked items to lay out for judgement")
    args = parser.parse_args()

    paths = get_paths(args.home) if args.home else get_paths()
    out_dir = paths.home / "p3"
    out_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(out_dir.glob("day-*.anon.json"))
    day = args.day if args.day is not None else len(existing) + 1
    previous = json.loads(existing[-1].read_text(encoding="utf-8")) if existing else None

    snapshot = build_snapshot(paths, day=day)
    snapshot["carry_over"] = carry_over(previous, snapshot)

    anon_path = out_dir / f"day-{day:02d}.anon.json"
    anon_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    sheet_path = out_dir / f"day-{day:02d}.sheet.md"
    sheet_path.write_text(_sheet(paths, snapshot, collect_tasks(paths), args.top), encoding="utf-8")

    print(json.dumps({"day": day, "anon": str(anon_path), "sheet": str(sheet_path),
                      "counts": snapshot["counts"], "carry_over": snapshot["carry_over"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
