# LifeAgent Case Study

## One-Line Summary

LifeAgent is an email-first personal operations agent that turns scattered life-admin messages into verified deadlines, cited answers, and confirmation-gated calendar actions.

## Problem

Important personal tasks rarely arrive as clean tasks. They arrive as email threads, attachments, account notices, and occasional portal pages:

- a rent or billing due date buried in a message
- a required action hidden in an attachment
- conflicting deadline copies across email and portal evidence
- a portal state that cannot be trusted because the session expired
- a calendar reminder that should not be written without user confirmation

The failure mode is high cost: the system says nothing, or answers confidently, while the current state was never verified.

## Product Decision

The project originally explored portal monitoring, but the stronger product direction is email-first:

```text
email evidence
-> deterministic extraction
-> source conflict detection
-> tool-first assistant answer
-> local calendar draft
-> confirmation-gated external write
```

Portals remain useful as fallback tools when an email says the official state is behind login, but they are not the main product surface.

## User Flow

1. The user ingests Gmail-style evidence or a local email export.
2. LifeAgent extracts deadline, amount, and action facts from message and attachment text.
3. The calendar view shows verified deadlines as local drafts by date.
4. The user asks a latest-fact question such as "What is my latest deadline?"
5. The assistant searches stored evidence and tool outputs before answering.
6. If sources conflict, it answers `uncertain`, cites evidence, and recommends the safer earlier deadline.
7. Calendar writes remain draft-first. ICS, Google Calendar, and Apple Calendar sync paths require explicit confirmation and replay protection.

## Architecture

```text
Email Intelligence Layer
  - local email JSON ingest
  - Gmail readonly connector boundary
  - attachment parsing
  - deadline, amount, action extraction

SentinelDesk Reliability Core
  - portal capture fallback
  - session health checks
  - deterministic diff
  - fail-loud critical/uncertain alerts
  - redacted evidence packages

Agent Assistant Layer
  - intent routing
  - tool registry with capability metadata
  - optional LangGraph route/tools/finalize workflow
  - model-provider abstraction
  - guarded model refinement only after verified answers

RAG Knowledge Layer
  - local SQLite index
  - trusted-doc retrieval
  - prompt-injection sanitization
  - explanation only, not latest-fact authority

Calendar Action Layer
  - local deadline drafts
  - dedupe/update planning
  - approval records
  - confirmation ID replay protection
  - ICS, Google, and Apple adapter boundaries
```

## Why This Is An Agent

LifeAgent uses an agent workflow where the assistant chooses and sequences tools before answering:

| Need | Mechanism |
| --- | --- |
| Latest deadline or amount | Tool-first email/evidence search |
| Missing official state | Portal capture fallback |
| Policy explanation | RAG over trusted docs |
| Calendar action | Draft, preview, confirm, then write |
| Model swap | Provider adapters and optional LangGraph workflow |
| Failure safety | `uncertain` instead of guessed answers |

The deterministic monitor core does not depend on LangChain, RAG, or an LLM to classify portal state. The agent layer uses those pieces where they fit: routing, retrieval, answer shaping, and model-provider flexibility.

## Safety Model

The project treats safety as product behavior, not a later cleanup step:

- Gmail is readonly by default.
- Secrets are referenced through environment-backed secret refs, not persisted in reports.
- Calendar writes require explicit confirmation.
- Approval records are durable and confirmation IDs cannot be replayed.
- Retrieved documents are treated as untrusted content.
- Redacted reports and ZIP packages remove emails, URLs, local paths, attachment names, invitees, connector cursors, and secret-like values.
- Release packaging excludes runtime artifacts, caches, local databases, screenshots, recordings, and share packages.

## Evidence

Current public checkpoint:

| Claim | Evidence |
| --- | --- |
| Extraction is regression-tested | 142-case golden email extraction eval |
| Raw extraction is clean on current synthetic set | deadline, amount, and action are all P=1.000 / R=1.000 / F1=1.000 |
| Behavior is covered beyond extraction | 264 unittest cases |
| Demo does not need private data | synthetic Gmail-style and portal fixtures |
| Share output is privacy-checked | redacted-output privacy audit passes |
| Public release excludes runtime artifacts | source release package + extracted release audit pass |
| CI is reproducible | GitHub Actions runs tests, eval, demo dry run, privacy audit, and release audit |

## Demo Scenario

The portfolio demo uses four synthetic Gmail-style messages:

- multiple deadline facts
- email-derived local calendar drafts
- reviewable tasks
- cited uncertainty for conflicting latest-deadline evidence
- secondary `/ops` view showing critical and uncertain portal fallback behavior

Run it locally:

```bash
cd sentinel-desk
python3 -B -m sentineldesk --home .demo demo record-prep --port 8787
python3 -B -m sentineldesk --home .demo serve --port 8787
```

Open:

- `http://127.0.0.1:8787/` for the calendar assistant
- `http://127.0.0.1:8787/ops` for the reliability/evidence dashboard

## GitHub Surface Copy

Recommended repository description:

```text
Email-first personal operations agent for deadlines, evidence, and calendar-safe actions
```

Recommended topics:

```text
agent, email, calendar, rag, langgraph, privacy, evals, python
```

## What I Would Discuss In An Interview

- The main product insight was moving from brittle portal-first monitoring to stable email-first evidence.
- The agent is useful because it can decide when to answer, when to retrieve, when to verify, when to draft, and when to refuse certainty.
- RAG is intentionally not used for latest facts; it is used for trusted explanations after tool evidence is available.
- Calendar writes are treated as side effects, so they require confirmation and audit records.
- The project has a real eval and privacy gate, not only a demo UI.
