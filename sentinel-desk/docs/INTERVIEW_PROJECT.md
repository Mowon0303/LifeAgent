# Interview Project: LifeAgent

## One-Liner

LifeAgent is an email-first personal operations agent that extracts high-risk deadlines, amounts, and actions from email evidence, verifies uncertain facts with tools, answers with citations, and drafts calendar actions behind explicit confirmation gates.

## Resume Bullets

- Built an email-first personal operations agent in Python that extracts deadlines, payment amounts, and required actions from Gmail-style evidence and attachments, then turns verified facts into local calendar drafts with source citations and explicit uncertainty.
- Designed a tool-first agent architecture with optional LangGraph workflow metadata, local RAG for trusted policy explanations, provider-swappable model adapters, and deterministic fallback tools for portal capture, session health, diffing, and fail-loud evidence bundles.
- Implemented safety and privacy gates for high-stakes personal data: readonly Gmail boundary, confirmation-gated calendar writes, durable approval records, replay protection, prompt-injection-resistant retrieval, redacted share packages, retention controls, and release-audit packaging.
- Added a reproducible evaluation and CI package: 296 unit tests, a 144-case golden email extraction eval with current raw deadline/amount/action P=1.000 and R=1.000, demo dry-run generation, redacted-output privacy audit, and source-release audit in GitHub Actions.

## 45-Second Explanation

LifeAgent solves a common personal-operations problem: important deadlines and actions are scattered across email threads, attachments, and sometimes portals. The agent does not just summarize messages. It extracts structured facts, checks for conflicts, answers latest-fact questions by calling tools first, and cites the evidence it used.

The architecture is intentionally split. Deterministic extraction and SentinelDesk's reliability core handle facts, portal fallback, health checks, and fail-loud alerts. The agent layer handles routing, tools, RAG-backed explanation, and optional model refinement. Calendar actions stay draft-first, and any external write requires explicit confirmation and an audit record.

## 2-Minute System Design Answer

The core product loop is:

```text
email evidence
-> deadline / amount / action extraction
-> source conflict detection
-> tool-first assistant answer
-> local calendar draft
-> confirmation-gated external write
```

Email is the primary input because most personal life-admin tasks arrive there first. The email layer persists local message evidence and extracted facts. For latest-deadline or latest-amount questions, the assistant must search stored evidence or call a verification tool before answering. If sources conflict, it returns `uncertain` and recommends the safer earlier deadline instead of making up a confident answer.

RAG is deliberately scoped to explanation. It retrieves trusted policy docs or prior evidence, sanitizes prompt-injection text, and provides citations, but it cannot override current tool evidence or trigger writes. The optional LangGraph layer is useful for route/tools/finalize workflow metadata and model-swappable orchestration, but the deterministic monitor core does not depend on LangChain, RAG, or an LLM.

The calendar layer is treated as a side-effect boundary. Extracted deadlines become local drafts first. ICS, Google Calendar, and Apple Calendar sync paths require explicit confirmation, dedupe/update planning, durable approval records, and replay protection.

## Architecture Talking Points

| Topic | Interview Answer |
| --- | --- |
| Why email first? | Stable signal source: deadlines, bills, school/admin notices, lease updates, and required actions usually arrive by email. Portal scraping is brittle and is better as a fallback verification tool. |
| Why not pure RAG? | RAG is not a source of truth for latest facts. Deadlines and amounts need extraction, source comparison, and tool verification. RAG is for policy explanation and evidence retrieval. |
| Where does LangGraph fit? | In the assistant orchestration layer: route intent, choose tools, finalize answers, and keep workflow metadata. It does not own deterministic alert decisions. |
| Where does the LLM fit? | Optional refinement over already verified answers. Uncertain answers and confirmation boundaries are not sent to the model for rewrite. |
| What makes it safer than a wrapper? | Tool capability metadata, explicit confirmation gates, durable approvals, replay protection, redacted outputs, local-first storage, evals, and privacy audits. |
| What is SentinelDesk now? | The reliability core: portal capture fallback, health checks, deterministic diff, fail-loud classification, and shareable evidence bundles. |

## Technical Proof

| Claim | Evidence |
| --- | --- |
| Extraction is evaluated | 144-case golden email extraction set |
| Current raw extraction is clean on synthetic eval | deadline, amount, and action P=1.000 / R=1.000 / F1=1.000 |
| Behavior is regression-tested | 296 unittest cases |
| CI is real | GitHub Actions runs unit tests, compile, eval, demo dry run, privacy audit, source release package, and release audit |
| Privacy is engineered | redacted-output audit and source-release audit are executable gates |
| Demo is public-safe | synthetic Gmail-style messages and synthetic portal fixtures; no real credentials or mailbox data required |

## Tradeoffs And Risks

- High-confidence extraction is conservative; this favors avoiding false positives over catching every possible low-confidence mention.
- Live Gmail readiness is useful, but public demos must stay synthetic and redacted.
- Calendar live writes are intentionally deferred unless the product workflow needs confirmed external sync.
- Portal fallback can be blocked by session expiry or anti-bot flows; the correct behavior is `uncertain`, not silent success.
- RAG quality depends on trusted local docs; missing docs should produce a refusal or uncertainty, not hallucinated policy advice.

## Demo Checklist

Run:

```bash
cd sentinel-desk
python3 -B -m sentineldesk --home .demo demo record-prep --port 8787
python3 -B -m sentineldesk --home .demo serve --port 8787
```

Show:

- calendar assistant at `http://127.0.0.1:8787/`
- email-derived deadline drafts by date
- assistant answer to "What is my latest deadline?"
- cited uncertainty and safer earlier deadline behavior
- `/ops` reliability dashboard with critical and uncertain portal runs
- redacted evidence report and package download
- GitHub Actions green CI

## Strong Interview Close

The point of this project is not that an LLM can read email. The point is that an agent for high-stakes personal tasks needs stable inputs, tool verification, failure-aware behavior, and side-effect controls. LifeAgent's architecture makes those boundaries explicit and testable.
