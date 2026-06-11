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

Open `http://127.0.0.1:8787/` for the LifeAgent calendar assistant page. Use `http://127.0.0.1:8787/ops` only as the secondary reliability/evidence view.

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

- Calendar assistant shows email-derived deadline drafts from the synthetic Gmail-style fixture.
- Demo prep persists 4 sample messages, 8 extracted facts, 3 calendar drafts, and reviewable tasks.
- Asking "What is my latest deadline?" returns an `uncertain` answer with `stored_email:` citations and the safest earlier candidate.
- Ops dashboard shows 3 targets.
- Ops recent runs include baseline, `critical`, and `uncertain` states.
- Alerts count is at least 2 after the action-required and session-expired scenarios.
- Evidence panel defaults to redacted evidence.
- `Open Report` opens the redacted HTML report.
- `Download Package` points to `/api/package/<run_id>` and downloads a redacted ZIP package.

## Voiceover Beats

1. Problem: important life-admin deadlines are scattered through email, attachments, and occasional portals.
2. Gmail-first: synthetic email evidence creates dated calendar drafts, amounts, and required actions.
3. Assistant: latest-deadline questions answer with citations and uncertainty when evidence conflicts.
4. Calendar layer: deadlines remain local drafts until the user confirms an export/write.
5. Reliability core: `/ops` shows fail-loud portal capture as a verification fallback, not the main product.
6. Evidence/privacy: redacted reports and packages are shareable; raw local evidence stays local.

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
- 4 sample email messages
- 8 extracted email facts
- 3 local calendar drafts
- 8 reviewable tasks
- baseline, `critical`, and `uncertain` states
- calendar assistant and ops dashboard load at `127.0.0.1:8798`
- `/api/calendar/events` returns 3 email-derived drafts
- `/api/ask` returns cited uncertainty for conflicting latest-deadline evidence
- redacted share package contents with no `file://` leak
