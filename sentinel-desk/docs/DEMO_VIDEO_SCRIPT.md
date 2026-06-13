# LifeAgent Demo Video Script

> **Status (archived 2026-06-12):** The recording direction was cancelled by user decision on 2026-06-12. This script is kept as archived/optional tooling only. The commands below remain executable, but recording is not in active scope.

Target length: 2 minutes.

## Setup

Use a clean demo home so the run history is easy to explain:

```bash
cd sentinel-desk
rm -rf .demo
python3 -m sentineldesk --home .demo demo record-prep --port 8787
python3 -m sentineldesk --home .demo serve --port 8787
```

Open `http://127.0.0.1:8787/` for the calendar assistant page. Use `/ops` as a secondary view for the deterministic SentinelDesk reliability core.

`demo record-prep` ingests synthetic Gmail-style sample emails for the calendar assistant, prepares baseline, critical, and uncertain portal states for `/ops`, then prints run IDs, report paths, package paths, and the serve command.

On macOS, you can run `bash scripts/record_portfolio_demo.sh` to prepare the demo, start the dashboard, open the browser, and record a 2-minute `.mov` file under `recordings/`. The script asks for explicit confirmation before recording; use `SENTINEL_RECORD_DRY_RUN=1 bash scripts/record_portfolio_demo.sh` to verify setup without recording.

## Voiceover

### 0:00-0:15 - Problem

LifeAgent is an email-first personal operations agent. The problem is that important deadlines, amounts, and required actions are scattered across inboxes, attachments, and occasional portals. A useful agent has to show evidence, say when it is uncertain, and avoid writing to calendars without confirmation.

### 0:15-0:40 - Gmail-First Calendar Surface

Here I start on the calendar assistant page. The demo ingested four synthetic Gmail-style messages. LifeAgent extracted deadlines, amounts, and required actions, then turned the verified deadline facts into local calendar drafts.

On screen:

- Show the month board with July 1 and July 2 email-derived deadlines.
- Point out source trust and draft state.
- Emphasize that these are local drafts, not external calendar writes.

### 0:40-1:05 - Cited Assistant Answer

Ask: "What is my latest deadline?"

The assistant returns an uncertain answer because multiple deadline facts exist. It cites the stored email evidence and chooses the safest earlier candidate instead of pretending one answer is definitely correct.

On screen:

- Show the uncertainty styling.
- Show the citation chips.
- State that the LLM/model path cannot override verified facts or confirmation boundaries.

### 1:05-1:30 - Calendar Confirmation Boundary

Show a pending calendar draft. The important behavior is not automatic scheduling. The system requires confirmation before external writes; local ICS/export and remote calendar sync use explicit approval gates.

### 1:30-1:45 - Reliability Core

Open `/ops`. SentinelDesk is the deterministic reliability core behind LifeAgent: portal capture, health checks, diffing, and fail-loud alerts. It is useful as a fallback when an email says "log in to see the official deadline," not as the main product surface.

On screen:

- Show baseline, `critical`, and `uncertain` runs.
- Show that session-expired states become `uncertain` instead of silent no-change.

### 1:45-1:55 - Evidence And Privacy

Every run writes raw evidence for local debugging plus redacted JSON, a redacted HTML report, and a redacted ZIP package for sharing. The dashboard defaults to redacted evidence, so file URLs and personal identifiers are not exposed in a portfolio demo.

The `Download Package` link exports the same redacted ZIP package as the CLI. The package excludes screenshots, DOM dumps, cookies, databases, and local paths.

Command:

```bash
python3 -m sentineldesk --home .demo evidence RUN_ID --redacted
python3 -m sentineldesk --home .demo evidence RUN_ID --report
python3 -m sentineldesk --home .demo evidence RUN_ID --package
```

### 1:55-2:00 - Architecture Close

The architecture is deterministic extraction and tool verification first, RAG for explanation over trusted docs, and model refinement only after verified answers. The product boundary is explicit: read and draft locally by default; external writes require confirmation.

## Shot Checklist

- Calendar assistant first screen with email-derived deadline drafts.
- Assistant answer with cited uncertainty.
- Pending calendar draft and confirmation boundary.
- Ops dashboard as the reliability-core secondary view.
- Critical and uncertain portal runs.
- Redacted evidence, HTML report, and ZIP package.
- Architecture diagram from `docs/ARCHITECTURE.md`.

## Common Interview Questions

| Question | Short answer |
| --- | --- |
| Why email first? | Most useful life-admin signals arrive by email; portals are a fallback when email says the official fact is behind login. |
| Why not just use RAG? | Deadlines and amounts are facts that need extraction and tool verification; RAG is for policy/docs explanation, not primary alerting. |
| Where does an LLM fit? | Only as a guarded rephrasing/refinement layer over verified answers; uncertain answers and calendar-write boundaries are not sent for rewrite. |
| Why local first? | Mail evidence, raw artifacts, credentials, and calendar drafts stay on the user's machine; share packages are redacted. |
