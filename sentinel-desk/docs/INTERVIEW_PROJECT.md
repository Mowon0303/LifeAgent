# Interview Project: SentinelDesk

## One-Liner

SentinelDesk is a local-first, fail-loud portal sentinel for high-stakes deadlines: it monitors application portals with deterministic checks, stores evidence bundles, and alerts when it cannot verify the state.

## Why It Is Different

Generic website monitors ask, "Did the page change?"

SentinelDesk asks, "Can I safely conclude there is no high-stakes action for the user?"

That distinction matters because a silent false negative is worse than no tool at all.

## Core Engineering Decisions

- Local first: real credentials and sessions stay on the user's machine.
- Fail loud: login expiry, captcha, bot block, short page, unknown status, or missing status markers produce `uncertain` alerts.
- Cheap first: normalized text hash, status extraction, deadline extraction, and structured diff run before any LLM.
- Evidence backed: every alert carries before/after text previews, status evidence, deadline candidates, health reasons, and diff preview.
- Portfolio safe: public demo uses synthetic portals only.

## Architecture Diagram

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full diagram. The short version is:

```text
capture -> visible text -> health check -> status/deadline facts -> diff + vertical policy -> evidence -> dashboard
```

## Demo Script

1. Seed synthetic OPT and appointment portal targets.
2. Run baseline checks.
3. Apply the `opt_action_required` scenario and run again.
4. Show a `critical` alert with evidence and deadline.
5. Apply `opt_session_expired` or `opt_redesign_unknown` and run again.
6. Show an `uncertain` alert proving fail-loud behavior.
7. Open dashboard and show the redacted evidence bundle, HTML report, and share package.

For a timed recording script, use [DEMO_VIDEO_SCRIPT.md](DEMO_VIDEO_SCRIPT.md). For final pre-recording checks, use [RECORDING_CHECKLIST.md](RECORDING_CHECKLIST.md).
For the public release boundary, use [PRIVACY_AUDIT.md](PRIVACY_AUDIT.md).

## Current Demo Surface

- `demo scenarios` lists public synthetic scenarios.
- `demo apply SCENARIO --run` applies a vertical transition and runs the watch, including OPT, appointment, and lease/rent scenarios.
- Dashboard controls can apply scenarios, run a target, toggle redacted evidence, open the generated report, and download the redacted share package.
- `cdp://127.0.0.1:9222/current?url=...` targets provide the real Chrome DevTools capture path for a detached dedicated local browser profile. If multiple tabs are open, CDP capture requires a deterministic `url`, `title`, or `id` selector.
- Real Chrome CDP dry-run has been verified against a synthetic OPT fixture, including screenshot artifact capture.

## Commercial Direction

Do not sell this as a horizontal webpage monitor. Start with one vertical where missed deadlines are expensive:

- OPT/USCIS/OIS status.
- Visa or Global Entry appointment slots.
- Lease or rent deadline portals, now represented by synthetic current, notice-required, and rent-due fixtures.
