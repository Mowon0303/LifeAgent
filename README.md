# LifeAgent

LifeAgent is an **email-first personal operations agent**. It finds high-risk deadlines, amounts, and required actions in email and attachments, verifies live facts with tools when evidence is insufficient, answers with citations and explicit uncertainty, and turns verified deadlines into a calendar surface where every external write requires confirmation.

**SentinelDesk** is the deterministic reliability core inside LifeAgent (portal capture, health checks, diffing, fail-loud alerts). Its founding rule still governs the whole project:

> If the system cannot verify the current state, it must say so instead of silently assuming nothing changed.

## Current Project

The active implementation lives in:

```bash
cd sentinel-desk
```

Run tests (expected: 217 pass):

```bash
cd sentinel-desk
python3 -B -m unittest discover -s tests -v
```

Run the extraction eval (golden set + report):

```bash
cd sentinel-desk
python3 -B -m sentineldesk eval email-extract --golden evals/golden --report-md docs/EVAL_REPORT.md
```

Run the Calendar + AI assistant page against synthetic demo data:

```bash
cd sentinel-desk
python3 -B -m sentineldesk --home /tmp/lifeagent-ui-demo init
python3 -B -m sentineldesk --home /tmp/lifeagent-ui-demo email scan --json fixtures/ui/sample_emails.json
python3 -B -m sentineldesk --home /tmp/lifeagent-ui-demo serve --port 8788
# open http://127.0.0.1:8788/  (calendar assistant is the main page; ops dashboard at /ops)
```

Run the monitor ops demo:

```bash
cd sentinel-desk
python3 -m sentineldesk --home .demo demo record-prep
python3 -m sentineldesk --home .demo serve --port 8787
# open http://127.0.0.1:8787/ops
```

## Key Documents

- [PLAN_TRACKER.md](PLAN_TRACKER.md) — architecture boundary, status table, safety verification matrix, next plan
- [sentinel-desk/docs/ARCHITECTURE.md](sentinel-desk/docs/ARCHITECTURE.md) — system diagram and safety boundaries
- [sentinel-desk/docs/UI_CONTRACT.md](sentinel-desk/docs/UI_CONTRACT.md) — backend ↔ calendar UI handoff contract
- [sentinel-desk/docs/EVAL_REPORT.md](sentinel-desk/docs/EVAL_REPORT.md) — extraction golden-set eval baseline
- [sentinel-desk/docs/SECURITY_MODEL.md](sentinel-desk/docs/SECURITY_MODEL.md) — trust boundaries and required controls
- [sentinel-desk/docs/PIVOT_POSTMORTEM.md](sentinel-desk/docs/PIVOT_POSTMORTEM.md) — blameless postmortem of the two product pivots
- `design_handoff_calendar_ai/` — user-provided visual design package (direction B′) that `/calendar` implements

## Privacy Boundary

Do not commit runtime state, real portal URLs, screenshots, DOM dumps, cookies, traces, or local database files. Public demos use synthetic fixtures only (`sentinel-desk/fixtures/`, `sentinel-desk/evals/golden/`). Before sharing source publicly, use `sentineldesk privacy release-package` and `privacy release-audit --require-clean`.
