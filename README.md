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
- **Eval:** 144-case golden email extraction set plus unit tests for orchestration, privacy, redaction, confirmation gates, and package shapes.

## Current Evidence

- `298` unittest cases pass.
- Golden extraction eval: raw deadline, amount, and action are all `P=1.000 / R=1.000 / F1=1.000` on the current synthetic set.
- Redacted Gmail-first readiness package shape is regression-tested.
- Daily landing workflow creates 4 synthetic messages, 8 extracted facts, 3 local calendar drafts, 7 grouped reviewable tasks, and a local audit record without external writes.
- Stored evidence reprocessing applies extractor fixes to already-synced mail without another Gmail call or external calendar writes.
- Task review groups same-email, same-kind facts into one UI item with `values` and `fact_count`, reducing a real `.demo` queue from 468 raw fact tasks to 112 grouped review items.
- Calendar assistant now reads `/api/daily/summary` on load and can run a local audited `/api/daily/run` from the UI without Gmail refresh or external calendar writes.
- Calendar assistant exposes amount/action task review cards with local-only `done`, `needs_verification`, `reviewed`, and `ignored` actions.
- Task cards can expand local source evidence from SQLite before review, including matched facts and a bounded email body preview, without refreshing Gmail or writing audit events.
- Task queues can be filtered by saved view/kind/status, sorted by priority/due date/recent activity, and navigated with previous/current/next controls, backed by `/api/tasks?view=&sort=&kind=&status=&limit=`.
- Task priority scores surface high-risk deadlines, low-confidence items, explicit `needs_verification` work, and payment/action context before low-risk review noise.
- Saved task views expose repeat review slices for `needs_verification`, `payments`, `deadlines_soon`, and `recently_changed`.
- Review-session summaries show current view progress, explain empty saved views, and offer the next non-empty review slice.
- Review receipt summaries show recent local task-review changes, net effective status counts, undo state, and latest action time without refreshing Gmail or writing external systems.
- Filtered task queues can be bulk-marked through a confirmation-gated local review API with single-use confirmation IDs and replay protection.
- Recent single/bulk task review actions have local history and confirmation-gated undo controls, so review mistakes can be recovered without external writes.
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

Run the repeatable daily landing workflow:

```bash
cd sentinel-desk
python3 -B -m sentineldesk --home .demo daily run --email-json fixtures/ui/sample_emails.json
```

For a real inbox, generate the local Google token first, then explicitly opt into readonly Gmail refresh:

```bash
python3 -B -m sentineldesk --home .demo daily run --sync-gmail --account user@example.com
```

`daily run` summarizes stored mail, extracted task queue, local calendar drafts, connector readiness, and next safe actions. It never performs external calendar writes.

Apply extractor fixes to already stored local evidence without another inbox refresh:

```bash
python3 -B -m sentineldesk --home .demo email reprocess --no-calendar-drafts
python3 -B -m sentineldesk --home .demo daily run --reprocess-stored --no-calendar-drafts
```

Run the extraction eval:

```bash
cd sentinel-desk
python3 -B -m sentineldesk eval email-extract --golden evals/golden --report-md docs/EVAL_REPORT.md
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
- [sentinel-desk/docs/INTERVIEW_PROJECT.md](sentinel-desk/docs/INTERVIEW_PROJECT.md) - resume bullets and interview talking points
- [sentinel-desk/docs/ARCHITECTURE.md](sentinel-desk/docs/ARCHITECTURE.md) - system diagram and safety boundaries
- [sentinel-desk/docs/UI_CONTRACT.md](sentinel-desk/docs/UI_CONTRACT.md) - backend to calendar UI handoff contract
- [sentinel-desk/docs/EVAL_REPORT.md](sentinel-desk/docs/EVAL_REPORT.md) - extraction golden-set eval report
- [sentinel-desk/docs/SECURITY_MODEL.md](sentinel-desk/docs/SECURITY_MODEL.md) - trust boundaries and required controls
- [sentinel-desk/docs/DEMO_VIDEO_SCRIPT.md](sentinel-desk/docs/DEMO_VIDEO_SCRIPT.md) - 2-minute demo script
- [sentinel-desk/docs/PIVOT_POSTMORTEM.md](sentinel-desk/docs/PIVOT_POSTMORTEM.md) - why the project pivoted from portal-first to email-first
