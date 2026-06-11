# Postmortem: Two Product Pivots in 36 Hours

**Status:** published · **Severity:** direction (no production incident; ~1 day of build work discarded) · **Date range:** 2026-06-10 → 2026-06-11 · **Author:** project owner, written blameless

## TL;DR

LifeAgent shipped three different product theses in 36 hours. Version 0.1.0 (JobOps Guard, a horizontal job-application toolkit) was deleted the same day it was scaffolded. Version 0.2.0 (SentinelDesk, a fail-loud portal monitor) survived as an engine but lost its position as the product within a day. The current thesis — an email-first personal operations agent with the monitor demoted to a verification tool — is the first one backed by data instead of intuition: a real Gmail sync showed where the signal actually lives.

The root cause of both pivots was the same: **capability-first development**. We built what we knew how to build (page capture, diffing, form tooling) and then went looking for a product story to wrap around it. Both times, the story collapsed on first contact with a hard question. The fix was procedural, not technical: every layer now has to earn its place with evidence (an eval baseline, a real sync, a user-accepted design) before the next layer goes on top.

## Timeline

| When (2026) | Event |
| --- | --- |
| 06-10 morning | 0.1.0 scaffolded: `jobops` package, React/Vite dashboard, Greenhouse/Lever/Workday fixtures, JD-vs-resume review, form inspection |
| 06-10 midday | Hard question #1: "What does this do that a job board plus a spreadsheet doesn't?" No defensible answer. Entire 0.1.0 surface deleted — package, frontend, fixtures, tests |
| 06-10 afternoon | 0.2.0: SentinelDesk. One falsifiable promise: *a monitor must alert when it cannot verify portal state, never silently assume "no change"*. Fail-loud classifier, evidence bundles, synthetic OPT/appointment/lease verticals |
| 06-10 evening | Hard question #2: "How often does a person actually need a high-stakes portal watched?" Low frequency, narrow audience. Portal monitoring demoted from product to tool; email-first LifeAgent thesis adopted |
| 06-11 | Real Gmail readonly sync (user-approved): 50 messages → 2,396 extracted facts → 184 deadline drafts. The signal-density bet confirmed empirically |
| 06-11 | Consolidation on the new thesis: 142-case extraction eval with regression gates; UI contract + calendar assistant page (user-provided design); guard-railed local-model loop with cost attribution. 230 tests |

## What broke, pivot by pivot

### Pivot 1 — JobOps Guard → SentinelDesk

**What broke:** the product was four products (portal watcher, JD reviewer, form filler, dashboard) sharing one repo and zero shared reason to exist. Each feature competed with an established free alternative, and none had a reliability or safety story the alternatives lacked.

**Why it happened:** the scaffold was generated from a capability inventory ("we can capture pages, we can parse JDs") rather than from a user moment. Breadth felt like progress because every direction produced visible code.

**Detection:** a single positioning question, asked out loud. Time-to-detect was hours — the cheapest part of the whole episode. The expensive part was that the question was asked *after* a full scaffold instead of before it.

### Pivot 2 — SentinelDesk-as-product → email-first LifeAgent

**What broke:** the core promise was sound (fail-loud verification is genuinely missing from generic page monitors) but the *surface area of need* was wrong. High-stakes portals (immigration cases, visa appointments, lease portals) change rarely and concern a narrow audience at any given moment. As the main product, SentinelDesk would have been a sentry with nothing to guard most days.

**Why it happened:** we anchored on the most technically interesting artifact (deterministic capture/diff/health pipeline) and assumed importance implied frequency. It does not. The deadline signal a person actually needs help with arrives daily, in email.

**Detection:** the demotion was a judgment call on 06-10, but the confirming evidence arrived 06-11: one Gmail sync over a real mailbox produced 2,396 dated/amount/action facts and 184 deadline drafts from 50 messages. No portal vertical comes within orders of magnitude of that density. This is the measurement that should have been taken first.

## The shared root cause

Both pivots are one failure mode: **build what you know, then search for why**. Symptoms that should have been caught as leading indicators:

1. The product description needed the word "and" three times (0.1.0).
2. No single user moment could be named where the tool beats the obvious alternative.
3. The roadmap was ordered by what was fun to engineer next, not by what evidence was missing next.

## What went right

- **Deleting instead of carrying.** Both pivots removed the dead surface completely (packages, fixtures, tests, frontend) in the same commit cycle. No zombie code influenced later design, and the 0.2.0 changelog records exactly what died and why.
- **The reliability core survived both pivots untouched.** Fail-loud classification, evidence bundles, and session-health detection moved from "the product" to "the verification tool" without rework — a sign that layer was built on a real invariant rather than a product guess.
- **Safety was never the discarded part.** Confirmation gates, audit trails, redaction, and capability-scoped tools transferred intact across all three theses, and ended up as the project's strongest differentiator.
- **Changelog discipline made this postmortem writable from records, not memory.**

## Prevention: what is now structurally different

| Mechanism | What it prevents |
| --- | --- |
| `PLAN_TRACKER.md` Response Condition: every status reply must state completed plans and the *single* next plan | Roadmap drift back into "build whatever is fun next" |
| Evidence column required for every Done row in the status table | Claiming progress without a verifiable artifact |
| Eval-first rule: the 142-case golden set and its regression gates existed before extraction improvements were scheduled | "Feels accurate" extraction; silent quality regressions |
| UI frozen until a user-provided design package arrived (and it did, as `design_handoff_calendar_ai/`) | Re-running pivot 1 with a prettier frontend |
| Model path is opt-in (`provider = "local"` by default) with anchors-preserved guardrails and per-call cost attribution | Capability-first creep returning via "just add an LLM" |
| Real-source milestones (actual Gmail sync, actual Ollama dry-run) gate each layer before the next | Building layer N+1 on an unvalidated layer N |

## Cost accounting

Roughly one day of build work was discarded across the two pivots (the 0.1.0 surface and SentinelDesk's product framing — though not its engine). Against that: the surviving system has a measured extraction baseline, a contract-tested UI on a user-chosen design, a guard-railed local model loop with cost attribution, and 230 passing tests. The pivots were cheap precisely because they happened in day one and two; the same wrong theses discovered a month later would have cost a month.

## Lessons (the portable ones)

1. **Ask the positioning question before the scaffold, not after.** "What does this beat, for whom, on which day of their life?" costs nothing and would have prevented 0.1.0 entirely.
2. **Importance is not frequency.** A high-stakes, low-frequency need makes a feature, not a product. Measure signal density before choosing the primary surface.
3. **Invariants travel, stories don't.** The fail-loud rule outlived every product framing around it. Invest early in the layer you can state as a falsifiable sentence.
4. **Make deletion a habit while it's cheap.** The willingness to remove a day-old scaffold whole is what kept either pivot from costing more than a day.
