# LifeAgent

[![CI](https://github.com/Mowon0303/LifeAgent/actions/workflows/ci.yml/badge.svg)](https://github.com/Mowon0303/LifeAgent/actions/workflows/ci.yml)

LifeAgent is an **email-first personal operations agent**. It reads local or Gmail-derived evidence, extracts high-risk deadlines, amounts, and required actions, answers questions with citations and explicit uncertainty, and turns verified deadlines into a local calendar surface where every external write requires confirmation.

The project is intentionally not a generic "agent wrapper." The reliability rule is:

> If the system cannot verify the current state, it must say so instead of silently assuming nothing changed.

## What It Does

- Extracts deadlines, amounts, and action items from emails and attachments.
- Answers latest-fact questions through tools first, with citations and uncertainty.
- Uses local RAG for trusted policy/docs explanations, not as the primary alerting mechanism.
- Drafts calendar events locally; ICS/Google/Apple calendar writes require explicit confirmation.
- Keeps SentinelDesk as the deterministic reliability core for portal fallback, health checks, diffing, fail-loud alerts, evidence bundles, and redacted share packages.
- Ships with synthetic fixtures, regression evals, and privacy checks so the repo can be reviewed without real inboxes, portals, cookies, or credentials.

## Architecture

```text
email / attachment / optional portal evidence
-> deterministic extraction and health checks
-> source conflict detection
-> tool-first assistant workflow
-> cited answer or explicit uncertainty
-> local calendar draft
-> confirmation-gated external write
```

Agent layer:

- **Tools:** email search, stored evidence reads, portal capture fallback, local calendar draft/export boundaries.
- **LangChain/LangGraph:** optional orchestration layer for route/tools/finalize workflow metadata and model-swappable tool routing.
- **RAG:** local SQLite-backed trusted document search for policy/rule explanation; retrieved prompt-injection text is sanitized.
- **Eval:** 142-case golden email extraction set plus unit tests for orchestration, privacy, redaction, confirmation gates, and package shapes.

## Current Evidence

- `264` unittest cases pass.
- Golden extraction eval: raw deadline, amount, and action are all `P=1.000 / R=1.000 / F1=1.000` on the current synthetic set.
- Redacted Gmail-first readiness package shape is regression-tested.
- Email-first demo dry run creates 4 synthetic messages, 8 extracted facts, 3 local calendar drafts, 8 reviewable tasks, and a cited uncertain latest-deadline answer.
- Source release packaging and release audit pass with runtime artifacts excluded.

## Portfolio Snapshot

Start with the [case study](sentinel-desk/docs/CASE_STUDY.md) for the product problem, architecture, agent boundaries, safety model, eval evidence, and GitHub repository description/topics.

## Quickstart

The implementation lives in `sentinel-desk/`.

```bash
cd sentinel-desk
python3 -B -m unittest discover -s tests -q
```

Run the email-first calendar assistant demo:

```bash
cd sentinel-desk
python3 -B -m sentineldesk --home .demo demo record-prep --port 8787
python3 -B -m sentineldesk --home .demo serve --port 8787
```

Open:

- `http://127.0.0.1:8787/` for the LifeAgent calendar assistant.
- `http://127.0.0.1:8787/ops` for the SentinelDesk reliability/evidence dashboard.

Run the extraction eval:

```bash
cd sentinel-desk
python3 -B -m sentineldesk eval email-extract --golden evals/golden --report-md docs/EVAL_REPORT.md
```

Run the recording prep without starting screen capture:

```bash
cd sentinel-desk
SENTINEL_RECORD_DRY_RUN=1 bash scripts/record_portfolio_demo.sh
```

## CI Gates

GitHub Actions runs:

- full unittest suite
- `compileall`
- golden extraction eval in JSON mode
- email-first demo dry run
- redacted-output privacy audit on generated demo artifacts
- source release package generation
- extracted source release audit

These checks require no real Gmail account, browser cookies, portal credentials, or external calendar writes.

## Privacy Boundary

Do not commit runtime state, real portal URLs, screenshots, DOM dumps, cookies, traces, OAuth tokens, local databases, or share ZIPs. Public demos use only synthetic fixtures under `sentinel-desk/fixtures/` and `sentinel-desk/evals/golden/`.

Before sharing source publicly:

```bash
cd sentinel-desk
python3 -B -m sentineldesk privacy release-package --source . --output /tmp/sentineldesk.release.zip
EXTRACT_DIR="$(mktemp -d /tmp/sentineldesk-release-audit.XXXXXX)"
python3 -B -m zipfile -e /tmp/sentineldesk.release.zip "$EXTRACT_DIR"
python3 -B -m sentineldesk privacy release-audit --path "$EXTRACT_DIR" --require-clean
```

## Key Documents

- [PLAN_TRACKER.md](PLAN_TRACKER.md) - architecture boundary, status table, safety matrix, next plan
- [sentinel-desk/README.md](sentinel-desk/README.md) - detailed CLI and developer workflow
- [sentinel-desk/docs/CASE_STUDY.md](sentinel-desk/docs/CASE_STUDY.md) - portfolio case study and GitHub surface copy
- [sentinel-desk/docs/ARCHITECTURE.md](sentinel-desk/docs/ARCHITECTURE.md) - system diagram and safety boundaries
- [sentinel-desk/docs/UI_CONTRACT.md](sentinel-desk/docs/UI_CONTRACT.md) - backend to calendar UI handoff contract
- [sentinel-desk/docs/EVAL_REPORT.md](sentinel-desk/docs/EVAL_REPORT.md) - extraction golden-set eval report
- [sentinel-desk/docs/SECURITY_MODEL.md](sentinel-desk/docs/SECURITY_MODEL.md) - trust boundaries and required controls
- [sentinel-desk/docs/DEMO_VIDEO_SCRIPT.md](sentinel-desk/docs/DEMO_VIDEO_SCRIPT.md) - 2-minute demo script
- [sentinel-desk/docs/PIVOT_POSTMORTEM.md](sentinel-desk/docs/PIVOT_POSTMORTEM.md) - why the project pivoted from portal-first to email-first
