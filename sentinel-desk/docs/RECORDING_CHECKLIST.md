# SentinelDesk Recording Checklist

Use this checklist before recording the 2-minute portfolio demo.

## Clean Demo Setup

Run from the project root:

```bash
cd sentinel-desk
rm -rf .demo
python3 -m sentineldesk --home .demo demo record-prep --port 8787
python3 -m sentineldesk --home .demo serve --port 8787
```

Open `http://127.0.0.1:8787/ops` (the monitor ops dashboard; `/` now serves the calendar assistant page).

`demo record-prep` prints the run IDs, report paths, package paths, expected dashboard URL, and serve command.

## One-Command Recording

On macOS, the helper script prepares the demo, starts the dashboard, opens the browser, waits 5 seconds, and records a 2-minute `.mov` file:

```bash
bash scripts/record_portfolio_demo.sh
```

The script asks you to type `record` before starting a real screen recording. Non-interactive runs must set `SENTINEL_RECORD_APPROVED=1` after reviewing the permission note.

Useful options:

```bash
SENTINEL_RECORD_DRY_RUN=1 bash scripts/record_portfolio_demo.sh
SENTINEL_RECORD_DURATION=120 bash scripts/record_portfolio_demo.sh
SENTINEL_RECORD_AUDIO=0 bash scripts/record_portfolio_demo.sh
SENTINEL_RECORD_OUTPUT=recordings/demo.mov bash scripts/record_portfolio_demo.sh
SENTINEL_RECORD_APPROVED=1 bash scripts/record_portfolio_demo.sh
```

macOS may ask for screen and microphone permissions. Recordings are written under `recordings/`, which is ignored by git.

Do not run the recording helper from an automation unless the user explicitly approves starting a real screen recording after seeing this permission note.

## Expected State

- Dashboard shows 3 targets.
- Recent runs include baseline, `critical`, and `uncertain` states.
- Alerts count is at least 2 after the action-required and session-expired scenarios.
- Evidence panel defaults to redacted evidence.
- `Open Report` opens the redacted HTML report.
- `Download Package` points to `/api/package/<run_id>` and downloads a redacted ZIP package.

## Voiceover Beats

1. Problem: silent false negatives are worse than no monitor.
2. Baseline: first verified snapshots are stored locally.
3. Meaningful change: OPT action-required status becomes `critical`.
4. Fail loud: session-expired state becomes `uncertain`.
5. Evidence: raw local evidence exists, but report/package outputs are redacted.
6. Architecture: capture, extraction, health, status/deadlines, diff, policy, evidence, dashboard.

## Privacy Check

Before sharing any artifact:

```bash
python3 -m sentineldesk --home .demo evidence RUN_ID --redacted
python3 -m sentineldesk --home .demo evidence RUN_ID --report
python3 -m sentineldesk --home .demo evidence RUN_ID --package
```

Confirm the redacted JSON, report, and package do not expose:

- real portal URLs
- `file://` URLs
- local filesystem paths
- screenshots
- cookies
- local databases

## Verified Dry Run

The latest dry-run used a temporary home outside the repo and verified:

- 5 demo runs
- 2 alerts
- baseline, `critical`, and `uncertain` states
- dashboard load at `127.0.0.1:8792`
- redacted share package contents with no `file://` leak
