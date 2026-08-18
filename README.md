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

Verified on 2026-08-14 both locally on Windows 11 (Python 3.11.9) and in CI on
`windows-latest` and `ubuntu-latest`
([run](https://github.com/Mowon0303/LifeAgent/actions/runs/32126171743), all 8
jobs green). Check the
[Actions tab](https://github.com/Mowon0303/LifeAgent/actions) for the current
state rather than trusting this list, or re-run the gates yourself with the
Quickstart below.

- `488` unittest cases pass, with `0` failures and `0` errors, on Windows and Linux.
- The suite is date-independent: it also passes with the product clock pinned to
  `2026-05-15`, `2026-12-29`, `2027-03-02`, `2028-02-29`, and `2031-11-07`. CI re-runs it
  daily and at ±1 and +5 years, so an expiring fixture fails a build instead of rotting quietly.
- Imported mail is loaded verbatim: the `{{today+N}}` tokens that keep the *synthetic*
  demo inbox from expiring are opt-in per call (`--fixture-dates`), so a real message
  containing that literal text still contains it after import.
- `acceptance first-run` returns `status: "passed"` at the current real date, reporting
  `external_network: false` and `external_writes_performed: false`.
- Golden extraction eval: 144 cases, `0` failures; raw deadline, amount, and action are all `P=1.000 / R=1.000 / F1=1.000` on the current synthetic set.
- High-confidence eval: deadline and amount are both `P=1.000 / R=1.000 / F1=1.000`; action confidence is intentionally flat until ranking needs action-specific tiers.
- Redacted Gmail-first readiness package shape is regression-tested.
- The local assistant exposes an explicit Gmail readonly sync/retry control with external-read labeling and redacted failure diagnostics.
- Daily landing workflow creates 4 synthetic messages, 8 extracted facts, 3 local calendar drafts, 7 grouped reviewable tasks, and a local audit record without external writes.
- Stored evidence reprocessing applies extractor fixes to already-synced mail without another Gmail call or external calendar writes.
- Task review groups same-email, same-kind facts into one UI item with `values` and `fact_count`, reducing a real `.demo` queue from 468 raw fact tasks to 112 grouped review items.
- Calendar assistant now reads `/api/daily/summary` on load and can run a local audited `/api/daily/run` from the UI without Gmail refresh or external calendar writes.
- The assistant shows a local-only Gmail first-run readiness checklist for OAuth env shape, optional dependencies, stored cursor, local evidence, and the next safe command.
- Gmail sync failures are classified into redacted local diagnostics with safe recovery commands, without returning raw OAuth errors, tokens, account IDs, cursors, or query text.
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
- Redacted artifacts contain no local filesystem paths: Windows drive paths
  (`C:\...`, `C:/...`, `D:\...`), UNC paths, their JSON-escaped spellings, POSIX
  home/temp paths, and **paths containing spaces** (`C:\Users\Jane Doe\...`) are all
  replaced with `[REDACTED_PATH]` with no fragment left behind, and the privacy audit
  detects an unredacted one instead of reporting clean.
- OAuth token files are written with verified owner-only access — `0o600` on POSIX, an
  owner-only DACL on Windows — and the write fails closed (the file is deleted) if that
  cannot be applied and re-verified. "Owner only" is stated precisely rather than
  overclaimed: on Windows, LocalSystem and Administrators retain access and cannot be
  excluded, exactly as root cannot be excluded by `0o600`. What is enforced is that no
  *other* principal (Authenticated Users, Users, Everyone, another account) can reach
  the file; inherited **and** explicit foreign entries are stripped, and verification
  reads the DACL back as SDDL so it does not depend on the OS display language.
- One-command first-run acceptance prepares the synthetic local MVP and verifies email ingest, task review, calendar draft visibility, tool-first cited ask behavior, Gmail readiness, UI wiring, audit logging, and no external network/write side effects.

### What is *not* verified

- No real Gmail account has been connected: Gmail readiness is `needs_oauth`, and every
  number above comes from synthetic fixtures. See
  [Verification levels](#verification-levels).
- No external calendar write has ever been performed.
- The multi-day product validation (is this worth using daily?) has not started.

## Portfolio Snapshot

Start with the [case study](sentinel-desk/docs/CASE_STUDY.md) for the product problem, architecture, agent boundaries, safety model, and eval evidence.

## Quickstart

The implementation lives in `sentinel-desk/`. LifeAgent needs **Python 3.11 or newer**
and no third-party packages for the core workflow.

### Windows (PowerShell)

```powershell
cd sentinel-desk
python -m venv .agent-venv
.\.agent-venv\Scripts\python.exe -m sentineldesk --home $env:TEMP\lifeagent-first-run acceptance first-run
.\.agent-venv\Scripts\python.exe -B scripts\run_tests.py
```

If `python` is not on your PATH, Windows may only have the Microsoft Store stub, which
opens the Store instead of running anything. Install a real runtime and use it directly:

```powershell
winget install Python.Python.3.11
& "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe" -m venv .agent-venv
```

Windows 11 also ships the Python install manager as `py`, which can fetch a specific
version and tell you where it landed:

```powershell
py install 3.11
py list --format=json
```

### macOS / Linux

```bash
cd sentinel-desk
python3 -B -m venv .agent-venv
.agent-venv/bin/python -m sentineldesk --home /tmp/lifeagent-first-run acceptance first-run
.agent-venv/bin/python -B scripts/run_tests.py
```

`scripts/run_tests.py` runs the same suite as `python -B -m unittest discover -s tests`,
but prints the final test count and fails loudly if a module failed to import or if
discovery collected less than the whole suite. To prove the suite is not date-dependent,
pin the clock:

```bash
python -B scripts/run_tests.py --now 2027-03-02
```

If the acceptance output says `status: "passed"`, open the prepared local assistant
(`.agent-venv\Scripts\python.exe` on Windows):

```bash
cd sentinel-desk
python3 -B -m sentineldesk --home /tmp/lifeagent-first-run serve --port 8787
```

Open:

- `http://127.0.0.1:8787/` for the LifeAgent calendar assistant.
- `http://127.0.0.1:8787/ops` for the SentinelDesk reliability/evidence dashboard.

Run the repeatable daily landing workflow:

```bash
cd sentinel-desk
python3 -B -m sentineldesk --home .demo daily run --email-json fixtures/ui/sample_emails.json --fixture-dates
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

## Verification levels

Three different things get called "verified" in this repo. They are not
interchangeable, and only the first one has actually been done:

| Level | What it proves | Status |
| --- | --- | --- |
| **Synthetic verification** | The workflow works end to end over `fixtures/` and `evals/golden/`: extraction, task queue, calendar drafts, cited answers, redaction, packaging. No account, no network. | Done — green on Windows and Linux, locally and in CI. |
| **Real Gmail readonly verification** | The same workflow over a real inbox, using an explicitly approved `gmail.readonly` OAuth scope. Needs the user's own Google credentials. | Not started — needs user authorization. |
| **External calendar write verification** | Writing a confirmed event to Google/Apple calendar. | Not started, and deliberately last. |

## CI Gates

GitHub Actions runs the following on **`ubuntu-latest` and `windows-latest`**, both on
Python 3.11, on every push and pull request, plus **daily on a schedule** so an expiring
fixture is caught without anyone committing:

- full unittest suite, via `scripts/run_tests.py` (prints the final count; fails if a module did not import)
- privacy regression tests (path redaction, privacy audit, evidence packages) as their own named step
- date-boundary regression tests as their own named step
- `compileall`
- golden extraction eval with `--require-clean`, so a failing case fails the build
- first-run MVP acceptance over synthetic local fixtures
- live verification preflight dry run (pure Python — the Windows leg needs no Bash)
- email-first demo dry run
- redacted-output privacy audit on generated demo artifacts
- source release package generation and extracted source release audit

A separate **date-rot guard** job re-runs the suite and acceptance on both platforms with
the product clock pinned to one year back, one year ahead, and five years ahead.

These checks require no real Gmail account, browser cookies, portal credentials, or external calendar writes.

## Privacy Boundary

Do not commit runtime state, real portal URLs, screenshots, DOM dumps, cookies, traces, OAuth tokens, local databases, or share ZIPs. Public demos use only synthetic fixtures under `sentinel-desk/fixtures/` and `sentinel-desk/evals/golden/`.

Local filesystem paths are redacted on every platform — Windows drive paths, UNC paths,
their JSON-escaped forms, and POSIX home/temp paths all become `[REDACTED_PATH]` in
redacted JSON, HTML reports, and share ZIPs.

Before sharing source publicly:

```bash
cd sentinel-desk
python3 -B -m sentineldesk privacy release-package --source . --output /tmp/sentineldesk.release.zip
EXTRACT_DIR="$(mktemp -d /tmp/sentineldesk-release-audit.XXXXXX)"
python3 -B -m zipfile -e /tmp/sentineldesk.release.zip "$EXTRACT_DIR"
python3 -B -m sentineldesk privacy release-audit --path "$EXTRACT_DIR" --require-clean
```

On Windows (PowerShell):

```powershell
cd sentinel-desk
$Extract = Join-Path $env:TEMP "sentineldesk-release-audit"
.\.agent-venv\Scripts\python.exe -B -m sentineldesk privacy release-package --source . --output $env:TEMP\sentineldesk.release.zip
.\.agent-venv\Scripts\python.exe -B -m zipfile -e $env:TEMP\sentineldesk.release.zip $Extract
.\.agent-venv\Scripts\python.exe -B -m sentineldesk privacy release-audit --path $Extract --require-clean
```

## Key Documents

- [PLAN_TRACKER.md](PLAN_TRACKER.md) - architecture boundary, status table, safety matrix, next plan
- [sentinel-desk/README.md](sentinel-desk/README.md) - detailed CLI and developer workflow
- [sentinel-desk/docs/CASE_STUDY.md](sentinel-desk/docs/CASE_STUDY.md) - portfolio case study
- [sentinel-desk/docs/INTERVIEW_PROJECT.md](sentinel-desk/docs/INTERVIEW_PROJECT.md) - resume bullets and interview talking points
- [sentinel-desk/docs/ARCHITECTURE.md](sentinel-desk/docs/ARCHITECTURE.md) - system diagram and safety boundaries
- [sentinel-desk/docs/UI_CONTRACT.md](sentinel-desk/docs/UI_CONTRACT.md) - backend to calendar UI handoff contract
- [sentinel-desk/docs/EVAL_REPORT.md](sentinel-desk/docs/EVAL_REPORT.md) - extraction golden-set eval report
- [sentinel-desk/docs/SECURITY_MODEL.md](sentinel-desk/docs/SECURITY_MODEL.md) - trust boundaries and required controls
- [sentinel-desk/docs/PIVOT_POSTMORTEM.md](sentinel-desk/docs/PIVOT_POSTMORTEM.md) - why the project pivoted from portal-first to email-first
