# SentinelDesk

SentinelDesk is a fail-loud local portal monitor for high-stakes deadlines.

It is not a generic website change detector. The core promise is:

> If the monitor cannot verify the portal state, it must alert instead of silently assuming nothing changed.

The first portfolio version uses synthetic OPT, appointment-slot, and lease/rent fixtures so the repo can be public without leaking real applications, screenshots, cookies, or personal records.

## What It Demonstrates

- Local-first portal monitoring using user-owned browser/session boundaries.
- Deterministic diff first; semantic interpretation only after a meaningful change.
- Session health checks for login expiry, captcha, bot blocks, server errors, and unknown status.
- Evidence bundles with before/after text previews, status, deadlines, health, and diff.
- A local dashboard for alerts, recent runs, evidence review, redacted reports, and redacted package downloads.
- Reliability tests focused on silent-failure prevention.

## Run The Demo

```bash
cd sentinel-desk
python3 -m sentineldesk --home .demo init
python3 -m sentineldesk --home .demo demo seed
python3 -m sentineldesk --home .demo demo scenarios
python3 -m sentineldesk --home .demo watch run
python3 -m sentineldesk --home .demo alerts
python3 -m sentineldesk --home .demo serve --port 8787
```

Open `http://127.0.0.1:8787`.

## Show A Meaningful Change

```bash
cd sentinel-desk
python3 -m sentineldesk --home .demo watch add \
  --name "Demo OPT Case" \
  --url "$(python3 - <<'PY'
from pathlib import Path
print((Path.cwd() / 'fixtures/portals/opt_action_required.html').resolve().as_uri())
PY
)" \
  --kind opt
python3 -m sentineldesk --home .demo watch run --name "Demo OPT Case"
python3 -m sentineldesk --home .demo alerts
```

Expected result: `critical` alert because the status changes to `action_required` and the deadline changes.

You can now run the same transition through the scenario helper:

```bash
python3 -m sentineldesk --home .demo demo apply opt_action_required --run
```

## Show Fail-Loud Behavior

```bash
cd sentinel-desk
python3 -m sentineldesk --home .demo watch add \
  --name "Demo OPT Case" \
  --url "$(python3 - <<'PY'
from pathlib import Path
print((Path.cwd() / 'fixtures/portals/session_expired.html').resolve().as_uri())
PY
)" \
  --kind opt
python3 -m sentineldesk --home .demo watch run --name "Demo OPT Case"
```

Expected result: `uncertain` alert because the portal state cannot be verified.

Other built-in scenarios include `opt_approved`, `opt_redesign_unknown`, `opt_session_expired`, `opt_maintenance`, `appointment_available`, and `appointment_captcha`.

Lease/rent scenarios include `lease_baseline`, `lease_notice_required`, and `lease_rent_due`.

## CLI Surface

```bash
python3 -m sentineldesk init
python3 -m sentineldesk doctor
python3 -m sentineldesk demo seed
python3 -m sentineldesk demo record-prep
python3 -m sentineldesk demo scenarios
python3 -m sentineldesk demo apply opt_action_required --run
python3 -m sentineldesk demo apply lease_notice_required --run
python3 -m sentineldesk targets
python3 -m sentineldesk watch add --name "My Portal" --url "https://example.com" --kind generic
python3 -m sentineldesk watch run --name "My Portal"
python3 -m sentineldesk runs
python3 -m sentineldesk alerts
python3 -m sentineldesk evidence RUN_ID
python3 -m sentineldesk evidence RUN_ID --redacted
python3 -m sentineldesk evidence RUN_ID --report
python3 -m sentineldesk evidence RUN_ID --package
python3 -m sentineldesk plan status
python3 -m sentineldesk plan status --json
python3 -m sentineldesk privacy audit --path .demo/artifacts --require-clean
python3 -m sentineldesk privacy release-audit --path . --require-clean
python3 -m sentineldesk privacy release-package --source . --output /tmp/sentineldesk.release.zip
python3 -m sentineldesk ask "When is my move-out notice deadline?" --email-json ./emails.json
python3 -m sentineldesk tasks list
python3 -m sentineldesk tasks review --task-id TASK_ID --status reviewed --note "Checked source evidence"
python3 -m sentineldesk calendar edit --event-id EVENT_ID --date 2026-07-03
python3 -m sentineldesk calendar sync --destination ics --event-id EVENT_ID --confirm
python3 -m sentineldesk serve
python3 -m sentineldesk chrome launch
```

The `ask` command is the first skeleton of the email-first LifeAgent assistant layer. It supports offline local JSON email fixtures, deterministic intent routing, email fact extraction, local RAG policy lookup, latest-run evidence lookup, and citation-bearing answers for deadline, amount, alert explanation, status meaning, next-step, and policy questions. It is intentionally tool-first: if no evidence is provided for a latest-fact or policy question, it returns `uncertain` instead of guessing.

The `tasks` commands expose the non-UI review layer for extracted LifeAgent work items. `tasks list` merges email facts and local calendar drafts into stable task IDs, and `tasks review` records `new`, `reviewed`, `ignored`, `needs_verification`, or `done` status with an audit event. The same backend is available through `/api/tasks` and `/api/tasks/review` for the future UI.

`chrome launch` starts a detached dedicated Chrome profile under `~/.sentineldesk/chrome-profile` and opens a blank page for the DevTools endpoint. SentinelDesk refuses default Chrome profile paths for remote debugging.

To capture a logged-in page through Chrome DevTools, launch the dedicated profile, open the portal tab there, then register a `cdp://` target:

```bash
python3 -m sentineldesk chrome launch
python3 -m sentineldesk watch add \
  --name "My OPT Portal" \
  --url "cdp://127.0.0.1:9222/current?url=https%3A%2F%2Fexample.edu%2Fportal" \
  --kind opt
```

If more than one debuggable tab is open, SentinelDesk refuses to guess. Use one of these selectors:

```bash
cdp://127.0.0.1:9222/current?url=https%3A%2F%2Fexample.edu%2Fportal
cdp://127.0.0.1:9222/current?title=OPT%20Case%20Portal
cdp://127.0.0.1:9222/current?id=CHROME_TARGET_ID
```

CDP runs save a local `.png` screenshot next to the HTML/text artifacts and record the screenshot path in raw evidence metadata. Redacted JSON and share packages redact local paths and intentionally exclude screenshot files.

The dashboard exposes the same privacy-safe package through `/api/package/<run_id>` and the `Download Package` link after a run is selected. It also shows local deadline drafts on the calendar board and lets the user adjust a draft date before confirmation-gated ICS/Google/Apple Calendar sync.

## Architecture

For the interview-ready diagram and talking points, see `docs/ARCHITECTURE.md`. For recording prep, use `docs/DEMO_VIDEO_SCRIPT.md` and `docs/RECORDING_CHECKLIST.md`. For the public sharing boundary, see `docs/PRIVACY_AUDIT.md`.

On macOS, `bash scripts/record_portfolio_demo.sh` prepares the demo, starts the dashboard, opens the browser, asks for explicit confirmation, and records a local `.mov` under `recordings/`.

For real Gmail/Calendar handoff, `python3 -m sentineldesk --home .demo integrations handoff --account user@example.com --output .demo/live-verification-handoff.md` writes the human checklist, and `bash scripts/live_verification_preflight.sh` runs the redacted live-readiness checks, package export, completion audit, redacted-output privacy audit, and final clean source release-package audit. Gmail sync, Google OAuth token flow, local verification draft seeding, and external calendar writes stay disabled unless explicitly enabled through `SENTINEL_LIVE_*` environment variables.

```text
target URL
-> fetch/capture
-> visible text extraction
-> session health check
-> status/deadline extraction
-> deterministic diff
-> fail-loud classifier
-> evidence bundle
-> dashboard + alerts
```

The current implementation is standard-library first so it runs without network dependency installation. The active extension plan is:

- Standard-library Chrome DevTools capture for real logged-in browser pages, with Playwright still possible later if the capture surface grows.
- Ollama semantic classifier only when deterministic diff detects a candidate change.
- Vertical portal packs for OPT/USCIS/OIS, appointment slots, or lease/rent deadline portals.
- Email-first intelligence for Gmail/email threads, attachments, deadlines, amounts, and action items.
- Calendar action layer that drafts deadline events, edits local draft dates, dedupes events, exports ICS, and requires confirmation before any external calendar write.
- LangChain/LangGraph assistant layer for model-swappable tool orchestration and RAG, without replacing the deterministic monitor core.

## Test

```bash
cd sentinel-desk
python3 -m unittest discover -s tests -v
```

The tests cover extraction, session health, fail-loud classification, CLI/database setup, Chrome launcher safety, deterministic Chrome CDP target routing, CDP screenshot artifacts, scenario transitions, lease/rent vertical behavior, dashboard smoke routes, evidence bundles, local calendar draft editing, evidence-backed `ask` answers, RAG-backed policy answers, redacted reports, redacted share packages, redacted-output privacy audit, project-tree release audit, clean source release packaging, dashboard package downloads, plan-tracker replies, and PII/path redaction.

## Privacy Boundary

Do not commit `.demo/`, `~/.sentineldesk/`, screenshots, DOM dumps, traces, real portal URLs or cookies. Public demos should use `fixtures/portals/*.html`.
