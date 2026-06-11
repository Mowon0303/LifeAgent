# LifeAgent Security Model

LifeAgent handles private life-admin data: email, attachments, deadlines, portal evidence, calendar entries, and model prompts. Security is therefore a product capability, not only an implementation detail.

## Trust Boundaries

| Boundary | Default | Escalation rule |
| --- | --- | --- |
| Email | Read-only ingest and search | Sending or labeling mail requires a separate write-capable scope and confirmation |
| Attachments | Local parsing and citation | Uploading or sharing attachments requires explicit confirmation |
| Portal capture | Local evidence capture and fail-loud alerts | Login, captcha, payment, upload, or form submission is outside the default monitor path |
| Calendar | Draft events and local previews | ICS export and Google/Apple sync require confirmation; Google/Apple writes also require a stable confirmation ID |
| RAG | Explanation over trusted/local evidence | Retrieved text cannot override verified facts or trigger write tools |
| Models | Local/rule path by default | Cloud provider calls must expose provider status, API-key env refs, and privacy choice |
| Reports | Redacted by default for sharing | Raw artifacts stay local and should not be committed or sent |

## Data Classes

| Data class | Examples | Storage rule |
| --- | --- | --- |
| Secrets | OAuth tokens, app passwords, API keys, cookies | Keep in env-backed references or local secret files; persist only redacted availability metadata |
| Private content | Email bodies, attachments, portal screenshots, calendar descriptions | Store locally; redact before share packages |
| Operational metadata | Connector cursor, OAuth scopes, sync status, approval records | Store locally for auditability; redact account-level identifiers in exported packages |
| Public/demo data | Synthetic scenarios, fixture pages, generated reports | Safe to include only after privacy audit confirms there is no real PII |

## Required Controls

1. Tool capabilities must declare whether they are read, draft, or write tools.
2. External writes must be blocked unless confirmation is present.
3. Confirmation IDs for external calendar writes must be single-use.
4. Every blocked or confirmed write path must create an audit event.
5. Confirmed writes must create a durable approval record with actor, action, capability, evidence refs, metadata, and confirmation ID.
6. Redacted share packages must remove secrets, local paths, email headers, attachment names, calendar invitees, connector cursor/account metadata, and sensitive IDs, then pass `privacy audit`.
7. Integration readiness reports must prove dependencies, granted OAuth scopes, cursors, and non-sandbox sync evidence without exposing secret values.
8. RAG content must be treated as untrusted input; instructions inside retrieved emails, PDFs, or webpages must not be executed.
9. High-stakes answers must cite evidence and return `uncertain` when facts conflict or current state cannot be verified.
10. Retention purge must preview counts first and require confirmation before deleting local records.

## Verification Standard

Local tests are not enough for release. A complete security verification package requires:

- unit tests for capability gating, confirmation blocking, replay protection, audit logging, redaction, RAG injection filtering, and source conflicts
- sandbox integration checks for Gmail and calendar adapter behavior without real credentials
- installed dependency checks for LangGraph and connector libraries
- a real Gmail OAuth sync that creates a non-secret connector cursor
- real Google Calendar and Apple Calendar sync evidence using confirmation-gated sandbox calendars
- a final `integrations check --suite all --require-ready --package` redacted ZIP
- a final `privacy audit --require-clean` scan over redacted reports and share packages

Until the real Gmail and calendar evidence exists, the project should be treated as locally implemented and sandbox-verified, not fully production-verified.
