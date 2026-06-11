# SentinelDesk Demo Video Script

Target length: 2 minutes.

## Setup

Use a clean demo home so the run history is easy to explain:

```bash
cd sentinel-desk
rm -rf .demo
python3 -m sentineldesk --home .demo demo record-prep --port 8787
python3 -m sentineldesk --home .demo serve --port 8787
```

Open `http://127.0.0.1:8787/ops` (the monitor ops dashboard; `/` now serves the calendar assistant page).

`demo record-prep` prepares baseline, critical, and uncertain demo states before recording, then prints the run IDs and artifact paths to use if needed.

On macOS, you can run `bash scripts/record_portfolio_demo.sh` to prepare the demo, start the dashboard, open the browser, and record a 2-minute `.mov` file under `recordings/`. The script asks for explicit confirmation before recording; use `SENTINEL_RECORD_DRY_RUN=1 bash scripts/record_portfolio_demo.sh` to verify setup without recording.

## Voiceover

### 0:00-0:15 - Problem

SentinelDesk is a local-first monitor for high-stakes portals. The problem is not just detecting page changes. The real failure is a silent false negative: the tool says nothing changed when the user was actually logged out, blocked by captcha, or looking at a redesigned page.

### 0:15-0:35 - Baseline

Here I start with synthetic OPT and appointment portals. The first run stores verified baselines. The dashboard shows local targets, recent runs, and evidence. There are no real portal URLs, cookies, screenshots, or personal records in the public demo.

Command:

```bash
python3 -m sentineldesk --home .demo watch run
```

### 0:35-1:00 - Meaningful Change

Now I apply an OPT action-required scenario. The status changes from submitted to action required, and the deadline candidate changes. SentinelDesk classifies that as a critical alert and writes an evidence bundle.

Command:

```bash
python3 -m sentineldesk --home .demo demo apply opt_action_required --run
```

Optional lease/rent variant:

```bash
python3 -m sentineldesk --home .demo demo apply lease_notice_required --run
```

On screen:

- Show the new `critical` run in Recent Runs.
- Click Evidence.
- Point out status evidence, deadline context, and diff preview.
- Open the redacted report or download the redacted package when showing a shareable artifact.

### 1:00-1:25 - Fail-Loud Uncertainty

Next I apply a session-expired scenario. A generic website monitor might treat this as just another page change or miss the real portal state. SentinelDesk marks it `uncertain` because it cannot verify the case status.

Command:

```bash
python3 -m sentineldesk --home .demo demo apply opt_session_expired --run
```

On screen:

- Show `uncertain`.
- Show the reason: login required or session expired.
- Say that uncertainty is intentionally surfaced instead of hidden.

### 1:25-1:45 - Evidence And Privacy

Every run writes raw evidence for local debugging plus redacted JSON, a redacted HTML report, and a redacted ZIP package for sharing. The dashboard defaults to redacted evidence, so file URLs and personal identifiers are not exposed in a portfolio demo.

The `Download Package` link exports the same redacted ZIP package as the CLI. The package excludes screenshots, DOM dumps, cookies, databases, and local paths.

Command:

```bash
python3 -m sentineldesk --home .demo evidence RUN_ID --redacted
python3 -m sentineldesk --home .demo evidence RUN_ID --report
python3 -m sentineldesk --home .demo evidence RUN_ID --package
```

### 1:45-2:00 - Architecture Close

The pipeline is capture, visible-text extraction, session health, status and deadline extraction, deterministic diff, vertical policy, and evidence. The important engineering choice is that health checks and unknown status can block "no change." That is what makes this a deadline sentinel instead of a generic webpage watcher.

## Shot Checklist

- Dashboard first screen with two demo targets.
- Baseline run list.
- Critical OPT action-required run.
- Evidence panel with deadline and diff preview.
- Uncertain session-expired run.
- Redacted evidence, HTML report, and ZIP package.
- Architecture diagram from `docs/ARCHITECTURE.md`.

## Common Interview Questions

| Question | Short answer |
| --- | --- |
| Why not just use a website monitor? | Website monitors optimize for change detection. SentinelDesk optimizes against silent false negatives in high-stakes portals. |
| Why local first? | Credentials, cookies, and real portal state stay on the user's machine. |
| Where would an LLM fit? | Only after deterministic diff finds a candidate change; never before health verification. |
| What is the first real vertical? | OPT/USCIS/OIS, because missed deadlines have concrete user cost. |
