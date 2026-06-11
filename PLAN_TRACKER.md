# LifeAgent Plan Tracker

Last updated: 2026-06-11

## Current Direction

LifeAgent now follows an **email-first personal operations agent** plan, with SentinelDesk kept as the reliability core for portal/tool verification.

Current project thesis:

> Build a local-first life operations agent that finds high-risk deadlines, amounts, and required actions from email, attachments, local evidence, and optional portal tools. The important capability is not generic webpage monitoring; it is turning scattered life-admin signals into verified tasks, reports, and a calendar surface the user can actually operate from.

Updated agent thesis:

> Use email and attachments as the primary signal source. Use tool calls to verify live facts when email evidence is insufficient or conflicting. Use RAG to explain policies and historical evidence. Use a calendar action layer to turn verified deadlines into visible reminders and confirmation-gated calendar writes. Keep SentinelDesk's deterministic monitor core for portal capture, health, diff, and alert decisions.

Active implementation:

```bash
sentinel-desk/
```

## Architecture Boundary

The project is now split into five layers:

```text
SentinelDesk Core
-> capture
-> visible text extraction
-> session health check
-> status/deadline extraction
-> deterministic diff
-> fail-loud classification
-> evidence bundles

Agent Assistant Layer
-> user question routing
-> tool verification for live facts
-> RAG over local evidence and trusted docs
-> model-provider abstraction
-> answer with citations, timestamps, and uncertainty

Email Intelligence Layer
-> Gmail/email search
-> attachment/PDF parsing
-> deadline/amount/action extraction
-> thread-level evidence bundles
-> conflict detection across messages and documents

Calendar Action Layer
-> draft deadline events
-> dedupe/update existing events
-> reminder policy
-> user confirmation before external calendar writes
-> dashboard calendar view

Safety and Governance Layer
-> tool allowlist with side-effect metadata
-> confirmation and durable approval records
-> replay protection for write confirmations
-> audit trail and retention controls
-> redacted live verification reports
```

Rules:

- Email and attachments are the default first source for personal life-admin deadlines.
- Portal monitoring is a verification/fallback tool, not the main product narrative.
- The monitoring core must not depend on LangChain, RAG, or an LLM to decide whether a portal changed.
- Questions about latest facts, such as deadlines, latest messages, amounts, or account status, must call tools first.
- RAG is allowed for explanation, policy lookup, historical evidence search, and answer synthesis.
- Calendar writes must be previewed as draft events first and require explicit user confirmation before syncing to Google Calendar, Apple Calendar, or ICS export.
- Calendar is a first-class product surface: verified deadlines should be visible by date, linked back to evidence, and marked as draft/synced/uncertain.
- If tools cannot verify the current state, the assistant must answer `uncertain`, not guess.
- User-facing answers should cite the exact run, evidence bundle, latest capture time, or retrieved document used.

## Source Priority

| Source | Role | Notes |
| --- | --- | --- |
| Email thread | Primary source | Most personal deadlines, billing notices, school/admin updates, leasing notices, and required actions arrive here first |
| Email attachment | Primary evidence | Lease PDFs, ledgers, policy PDFs, invoices, school forms, and notices often contain the authoritative clause |
| Local evidence history | Memory of verified facts | Tracks prior extracted deadlines, amounts, confidence, and source conflicts |
| Portal/CDP capture | Verification tool | Use when email says "log in to view", when ledger/status is only visible online, or when sources conflict |
| Trusted docs/RAG index | Explanation source | Use for interpreting rules, policy docs, lease clauses, and prior evidence, not for unverified current facts |
| Calendar | Action and visibility layer | Shows verified deadlines and reminders by date; not treated as a source of truth unless linked back to evidence |

## Question Routing Plan

| User Question Type | Required Path | Example Tools | RAG Use |
| --- | --- | --- | --- |
| Latest deadline or latest message | Tool verification first | `search_latest_email`, `parse_attachments`, `capture_latest_portal`, `extract_deadlines` | Only for explanation after the fact is verified |
| Latest balance, bill, or amount due | Email/attachment first, portal if needed | `search_latest_email`, `parse_statement`, `capture_latest_portal`, `extract_amounts` | Optional explanation over evidence |
| Why did this alert fire? | Evidence lookup | `read_evidence_bundle`, `read_diff`, `read_trace` | Optional summary over evidence |
| What does this status mean? | Verified status + docs | `read_latest_run`, `search_policy_docs` | Yes, cite trusted docs |
| What should I do next? | Tool + docs + task/calendar recommendation | `search_latest_email`, `capture_latest_portal`, `extract_deadlines`, `search_policy_docs`, `draft_calendar_event` | Yes, with uncertainty guard |
| Put this on my calendar | Draft then confirm | `draft_calendar_event`, `dedupe_calendar_event`, `sync_calendar_event` | No, unless explaining source evidence |
| Did the page change? | Monitoring core only | `capture_latest_portal`, deterministic diff | No |
| General policy question | Docs retrieval | `search_policy_docs`, `search_local_docs` | Yes |

## Response Condition

- Rule: Every plan-status reply must show completed plans and the next plan to complete.
- Completed plans: Read from the `Status Table` rows whose `Status` is `Done`.
- Next plan to complete: UI implementation is paused until the user provides a design reference package. The next non-UI plan is to turn the Gmail-first task/evidence backend into a stable handoff contract for that UI package: documented response shapes, redacted sample fixtures, and regression tests around task review plus citation payloads. Calendar live writes remain deferred unless the product workflow needs confirmed external calendar sync.

## Status Table

| Area | Status | Evidence | Next Work |
| --- | --- | --- | --- |
| Project cleanup | Done | Old `jobops/`, `frontend/`, root job fixtures, old tests, root `pyproject.toml`, runtime artifacts, and remaining SentinelDesk job fixtures removed | Keep root as a lightweight project hub; implement inside `sentinel-desk/` |
| SentinelDesk package | Done | `sentinel-desk/sentineldesk/*`, including optional `cdp://` Chrome DevTools capture with screenshot artifacts and detached Chrome launcher | Keep public demo synthetic unless real portal dry-runs are explicitly needed |
| Synthetic high-stakes fixtures | Done | `sentinel-desk/fixtures/portals/*.html`, `sentineldesk/scenarios.py`, including OPT, appointment, and lease/rent scenarios | Add more lease/rent edge cases only after real dry-runs |
| Fail-loud classifier | Done | Handles session expired, captcha, maintenance, capture errors, unknown high-stakes status, meaningful changes, irrelevant changes | Tune vertical policies from real user dry-runs |
| Evidence bundles | Done | Each run writes raw evidence JSON, redacted JSON, redacted HTML report, optional CDP screenshot artifacts, CLI share package, and dashboard share package download; redacted exports include structured handling for email headers, attachment names, calendar invitees, secrets, and connector metadata | Keep screenshots excluded from redacted share packages |
| Dashboard | Done | Local dashboard has target runs, scenario apply/apply+run controls, redacted evidence toggle, report link, package download link, month/week/day calendar board for email-derived deadlines, calendar draft preview, approval history preview, retention preview/confirmed purge controls, audit event count, approval count, connector state count, integration verification count, and confirmation-gated local ICS export for calendar drafts | Keep download and retention controls as stable preview-first actions |
| Reliability tests | Done | 191 unittest cases pass in `sentinel-desk/tests`, covering email/calendar extraction, task review backend, dashboard APIs, retention/audit/approval gates, privacy/release packaging, RAG safety, model/provider boundaries, LangGraph-shaped workflow metadata, tool-verified latest facts, portal fallback citation chaining, CLI `ask`, and Gmail-first integration readiness reports | Re-run before publishing |
| Commercial alignment | Done | Product narrative pivoted from portal-first monitoring to email-first personal operations with portal/CDP as a verification tool and calendar as the action layer | Keep demos focused on email-derived deadlines, lease/rent admin, billing, and calendar reminders |
| Interview presentation polish | Done | `docs/ARCHITECTURE.md`, `docs/DEMO_VIDEO_SCRIPT.md`, and `docs/RECORDING_CHECKLIST.md` added | Record a 2-minute portfolio demo using the script |
| CDP hardening | Done | CDP target selection now allows auto-selection only for a single page and otherwise requires deterministic `url`, `title`, or `id` selectors; real Chrome CDP dry-run captured a synthetic OPT fixture successfully | Record a portfolio demo using the verified path |
| CDP screenshot artifact capture | Done | CDP captures call `Page.captureScreenshot`, write local `.png` artifacts, and store screenshot paths in raw evidence metadata while redacted evidence removes local paths | Add report thumbnail/preview only if screenshot review becomes useful |
| Dashboard smoke test | Done | `tests/test_dashboard_smoke.py` verifies scenario apply+run, redacted evidence, report endpoints, retention UI controls, and retention preview/confirmed purge API without binding a port | Add browser-driven smoke only if dashboard UI grows beyond static controls |
| Evidence export packaging | Done | `python3 -m sentineldesk evidence RUN_ID --package` writes a redacted ZIP with README, manifest, JSON evidence, and HTML report | Keep CLI and dashboard package contents aligned |
| Dashboard package download route | Done | `/api/package/<run_id>` creates and returns the same redacted share ZIP as an attachment, and the dashboard enables a `Download Package` link for selected runs | Keep CLI and dashboard package contents aligned |
| Browser-driven dashboard smoke | Done | Local server on `127.0.0.1:8791` verified scenario selection, Apply + Run, redacted evidence, report opening, package link enablement, and stable package-link click behavior in the in-app browser | Re-run after major dashboard UI changes |
| Real Chrome CDP dry-run | Done | Dedicated Chrome DevTools endpoint captured synthetic OPT fixture through `cdp://127.0.0.1:9223`, producing health `ok`, status `submitted`, baseline alert, HTML/text artifacts, and a 99,900-byte screenshot artifact | Re-run only when CDP capture changes |
| Portfolio demo recording pass | Done | Clean demo pass in a temporary home outside the repo produced 5 runs, 2 alerts, baseline/critical/uncertain states, dashboard load, and a redacted share package with no `file://` leak; `docs/RECORDING_CHECKLIST.md` captures the final recording checklist | Run public release privacy audit before sharing |
| Public release privacy audit | Done | `sentineldesk privacy release-audit --path sentinel-desk` detects local ignored development artifacts (`.agent-venv`, `sentineldesk.egg-info`, and `__pycache__/` directories), while `sentineldesk privacy release-package --source sentinel-desk --output /private/tmp/.../sentinel-desk.release.zip` excludes those artifacts; the extracted release ZIP passed `privacy release-audit --require-clean` with 91 scanned files and 0 issues | Use `privacy release-package` rather than direct local-tree zipping for public sharing |
| Manual demo recording handoff | Done | `python3 -m sentineldesk --home .demo demo record-prep --port 8787` now prepares the full recording state, prints run IDs/report/package paths, and is covered by CLI tests; `docs/DEMO_VIDEO_SCRIPT.md` and `docs/RECORDING_CHECKLIST.md` use the new flow | User records the actual video with local screen/audio permissions |
| User-operated screen recording helper | Done | `scripts/record_portfolio_demo.sh` prepares `.demo`, starts the dashboard, opens `127.0.0.1:8787`, waits 5 seconds, and invokes macOS `screencapture` for a 2-minute `.mov`; recordings are ignored by git | User runs the helper and grants local screen/audio permissions |
| Screen recording approval guard | Done | Recording helper now requires interactive `record` confirmation or `SENTINEL_RECORD_APPROVED=1`; `SENTINEL_RECORD_DRY_RUN=1` verified setup without recording, and unapproved non-interactive execution exits before capture | Await explicit user approval to record |
| Lease/rent vertical | Done | `lease_current.html`, `lease_notice_required.html`, `lease_rent_due.html`, lease scenarios, status extraction, and demo seed target added | Add more lease/rent edge cases only after real dry-runs |
| Agent architecture boundary | Done | Plan now explicitly separates deterministic monitor core from LangChain/LangGraph assistant layer | Keep alert decisions out of LLM/RAG paths |
| LangChain/LangGraph assistant skeleton | Done | `sentineldesk/agent/` now has schemas, intent router, tool registry, optional model-provider detection, retrieval skeleton, graph-style `answer_question`, multi-stage `answer_with_workflow` metadata, route/tools/finalize workflow trace, optional LangGraph route/tools/finalize graph builder, `sentineldesk ask` CLI metadata, evidence-backed alert explanation/status meaning/next-step recommendation over latest local runs, optional `agent` dependencies, real installed `langgraph.graph` availability, `CompiledStateGraph` workflow build evidence, and `integrations check --suite langgraph --require-ready` ready evidence from the project-local `.agent-venv` | Keep deterministic monitor decisions outside the LangGraph/RAG path |
| Tool verification layer | Partial | Tool registry defines read/draft/write capabilities and blocks `sync_calendar_event` without confirmation; `ask` forces email search for latest deadline/amount questions; email-only deadline misses can fall back to bound `capture_latest_portal` when email says to log in or view the portal; `ask` also reads latest local evidence through `read_evidence_bundle` for alert explanations, status meanings, and next-step recommendations; `email scan --json` creates local evidence without external writes; `email sync-gmail` defines the authenticated Gmail path; calendar tools remain draft-first and confirmation-gated; `capture_latest_portal` is bound to the deterministic monitor core for page-change questions; `integrations google-token` writes Google token JSON to a local 0600 file without printing it; `integrations check --suite gmail --require-ready --package` produced ready Gmail-first evidence after a real readonly sync of 50 messages, 2396 extracted facts, 184 local deadline drafts, and a saved connector cursor; `privacy audit --require-clean` passed on redacted packages; `integrations seed-calendar-draft` can create a local-only verification draft for future calendar testing; `integrations completion-audit` and `integrations handoff` still document the stricter all-suite path for a later Calendar milestone | Calendar live writes are deferred; if useful later, verify a single seeded Google/Apple draft with explicit confirmation, then rerun all-suite readiness and completion audit |
| RAG knowledge layer | Done | `sentineldesk/agent/retrieval.py` provides citation-oriented search with prompt-injection detection/sanitization, trust-label weights, sparse lexical vector ranking metadata, and retrieval context metadata; `sentineldesk/agent/rag_index.py` persists local documents/chunks in SQLite and returns document source, title, token count, score, matched terms, and trust weight; CLI supports `rag index/search/docs`, `--title`, `--trust-label`, and repeated `--metadata key=value`; `ask` routes policy/rule questions through `search_policy_docs`, returns citations, and refuses to answer when no local RAG evidence exists; evals prove trusted policy docs outrank untrusted matches and prompt-injection text is sanitized before answer synthesis | Consider dense embedding adapters only after model-provider privacy and dependency choices are finalized |
| Model provider abstraction | Done | `sentineldesk/agent/model.py` reads `[model]` config for provider/model/base_url/api_key_env/privacy/structured_output and detects optional `langchain_core`/`langgraph`; `sentineldesk/agent/providers.py` defines local, Ollama, OpenAI, and Anthropic adapter boundaries, request shapes, redacted env-secret status, JSON schema hints, and `AgentAnswer` structured output validation; `model status` includes safe adapter status and redacted API-key refs; `pyproject.toml` exposes optional `agent` dependencies | Exercise real model calls only after provider/privacy choices and credentials are explicitly approved |
| Agent eval suite | Partial | `tests/test_email_calendar_agent.py`, `tests/test_safety_connectors.py`, `tests/test_agent_orchestration.py`, `tests/test_authenticated_integrations.py`, `tests/test_live_verification.py`, `tests/test_privacy_audit.py`, and dashboard smoke tests cover routing, forced email search, uncertainty, calendar confirmation, local calendar draft edit/reschedule, tool registry safety, source conflicts, cross-source stored conflict detection, CLI ask, evidence-backed alert explanation, status meaning, next-step recommendation, RAG-backed policy answer citations, bound portal capture execution for page-change questions, email-to-portal deadline fallback when email says to log in, email scan persistence, calendar draft APIs, dashboard ICS sync, dashboard retention preview/confirmed purge, connector trust labels, connector cursor state, fake-authenticated Gmail sync, fake Google/Apple calendar sync, sandbox connector/calendar verification report persistence, live verification report persistence, redacted-output privacy audit, completion-audit privacy requirement failure, human handoff Markdown redaction/approval/side-effect coverage, env-template/preflight source release gate commands and completion-audit source-release-path redaction, retention gates, audit logs, persistent RAG, trust-weighted RAG ranking, model config, safe model provider adapters, structured output validation, real installed LangGraph workflow readiness, rule/LangGraph-shaped multi-stage workflow metadata, RAG injection filtering, and retrieved-instruction resistance against verified deadline override and calendar write-tool triggering; live Gmail-first verification artifacts now prove the authenticated readonly path outside fake clients | Add eval fixtures around the redacted Gmail-first package shape; keep Calendar live-write evals deferred until Calendar becomes useful |
| Email intelligence layer | Done | `sentineldesk/email/` models local email messages, loads local JSON exports, parses local text/HTML/PDF attachments when parsers are available, searches messages through connector abstractions, extracts deadlines/amounts/actions from body/attachment text, persists extracted facts in `email_messages`, labels source trust, audits local ingest, defines `email sync-gmail`, saves connector cursor state, tracks OAuth scopes without storing secrets, has `integrations check --suite gmail` readiness reports including redacted Gmail credentials/token format and token-scope validation, exposes installed `gmail`/`integrations` optional dependencies including `google-auth-oauthlib`, includes `integrations env-template` and `integrations google-token` for Gmail env refs/token generation/sync commands, has sandbox Gmail sync verification through `integrations check --suite sandbox`, and passed real user-approved Gmail readonly sync with 50 messages persisted, 2396 facts extracted, 184 local deadline drafts, a saved connector cursor, and ready redacted package `20260611T130933+0000-gmail.share.zip` | Keep Gmail as the current primary live source; add portal fallback evidence only for emails that say the user must log in to see the official deadline |
| Task review backend | Done | `sentineldesk/tasks.py` aggregates email facts and local calendar drafts into stable reviewable tasks without duplicating deadline facts already represented by draft events; `task_reviews` persists `new/reviewed/ignored/needs_verification/done` status, note, actor, and timestamp; `sentineldesk tasks list/review`, `/api/tasks`, and `/api/tasks/review` expose the backend contract for the future UI; review changes write `task.review` audit events and retention supports the `tasks` source | Wait for the user-provided UI design package, then connect the visual task-review surface to the existing API |
| Calendar action layer | Partial | `sentineldesk/calendar/` defines `DeadlineEvent`, reminder rules, draft generation from facts, dedupe/update planning, confirmation gate, ICS export, persisted `calendar_drafts`, `/api/calendar/drafts`, `/api/calendar/events`, dashboard month/week/day calendar board, local draft editing through `calendar edit`, `/api/calendar/drafts/update`, and dashboard `Save Date`, confirmation-gated calendar adapters, `/api/calendar/sync`, dashboard ICS export, `calendar sync --destination ics/google/apple`, fake Google/Apple remote client boundaries, remote list/update/create upsert behavior, created/updated external ID audit metadata, installed `calendar`/`integrations` optional dependencies, sandbox Google/Apple calendar verification through `integrations check --suite sandbox`, redacted Google Calendar token scope validation, live calendar readiness checks for non-sandbox confirmed sync approval records, and audit logging for local edits plus blocked/confirmed sync; a local seeded draft exists for later live verification, but no external calendar write was performed | Deferred by product decision; keep local calendar board/drafts visible, but do not require Google/Apple live sync for the Gmail-first milestone |
| Calendar visual system | Done | `sentineldesk/calendar/view.py` normalizes draft dates into `date_key`; `/api/calendar/events` merges calendar drafts with approval/sync state; dashboard renders month/week/day views with dated deadline chips, source trust, draft/synced status, uncertainty styling, evidence tooltip, local draft date editing, and confirmation-gated ICS export; Chrome smoke verified the July 2, 2026 deadline chip on the calendar board | Add richer timezone/reminder editing only after real connector behavior is validated |
| Calendar confirmation flow | Partial | `plan_calendar_sync`, `sync_calendar_draft`, `/api/calendar/sync`, and `sentineldesk calendar sync` block calendar writes unless `confirmed=True`; CLI Google/Apple external writes also require a stable `--confirmation-id`; dashboard uses a user confirmation before local ICS export; local date edits reset synced drafts back to `draft`/`local_draft` and audit `calendar.edit` without creating approval records; blocked and confirmed attempts are recorded in `audit_events`; confirmed writes create `approval_records`; reused confirmation IDs are blocked before a second write; users can inspect approvals through `sentineldesk approvals list`, `/api/approvals`, dashboard approval count, and dashboard approval history preview; `ask` returns confirmation boundary for calendar requests | Keep production external-write dry-runs deferred until Calendar is a chosen user workflow |
| Source conflict detection | Done | `sentineldesk/agent/conflict.py` detects conflicting deadline/amount evidence, collects normalized local facts from email messages, calendar drafts, and portal run evidence, and returns the safer earliest deadline candidate; assistant returns `uncertain` for direct evidence conflicts; tests prove email/calendar July 2 evidence conflicts with portal July 15 evidence and picks July 2 as safest | Expand source weighting only after live connector evidence is available |
| Safety capability plan | Partial | Tool capabilities, calendar confirmation gate, local calendar edit audit/reset, task review audit trail, durable approval records, approval replay protection, approval history API/CLI/dashboard preview, source citations, local-first persisted email/calendar drafts/task review state, read-only dashboard APIs, source-trust labels, audit events, CLI/API/dashboard retention preview with confirmation-gated purge including approvals and task reviews, dashboard ICS confirmation, env-only secret refs, connector cursor state, redacted sandbox/live verification reports, unique integration verification IDs for repeated same-second checks, strict `completion-audit` final package/readiness/privacy/source-release gate, human-readable `integrations handoff` approval/side-effect checklist, redacted-output `privacy audit` gate, project-tree `privacy release-audit` gate, clean source `privacy release-package` export, redacted Google OAuth credential/token format and token-scope checks, redacted Apple Calendar username/app-password format checks, live calendar sync-evidence checks that ignore sandbox approvals, redacted live env template output, redacted integration verification packages, local Google token writer that does not print token values and writes 0600 files, real Gmail readonly sync evidence, a ready Gmail-first package, clean redacted-output privacy audit, default-safe `scripts/live_verification_preflight.sh` source release gate, structured share-package redaction for email headers/attachments/invitees/connector metadata, RAG prompt-injection filtering, retrieved-instruction resistance for verified facts and write tools, email-to-portal deadline fallback, bound portal capture as a local evidence-write tool, real installed LangGraph readiness evidence, remote calendar duplicate/update-before-create evals, and `docs/SECURITY_MODEL.md` security acceptance criteria are implemented | Recheck redaction after any new real source type; Calendar safety evidence remains later because external writes are deferred |

## Current Non-UI Backend Checkpoint

- UI implementation remains paused pending the user-provided design reference package.
- Current backend focus: Gmail-first question answering, tool-verified latest facts, portal fallback only when email evidence says the user must log in or view the portal, and calendar as a local action/visibility layer.
- Latest portal fallback work: deadline fallback answers now cite both the portal run and the triggering email, carry `email_to_portal_deadline` metadata, preserve `planned_tools_initial`, and merge runtime fallback calls into workflow `planned_tools`.
- Latest eval coverage: targeted orchestration/email tests cover verified portal deadlines, uncertain session-expired portal fallbacks, CLI `ask` fallback output, and workflow metadata that records runtime `capture_latest_portal`.

## Safety Capability Plan

Security and safety are product features for this project, not only implementation hygiene.

| Safety Area | Required Capability | Reason |
| --- | --- | --- |
| Permission boundaries | Separate read, draft, and write permissions for email, portal, docs, and calendar tools | Prevents a question-answering flow from silently mutating user data |
| OAuth scope control | Store and display granted scopes, keep Gmail on readonly by default, and require explicit upgrade for write/send scopes | Lets the user see exactly what an integration can do before enabling it |
| Secret handling | Keep OAuth tokens, app passwords, cookies, and API keys in environment-backed secret references; persist only redacted availability metadata | Prevents databases, reports, and share packages from becoming credential stores |
| Live verification artifacts | External integration checks must write redacted readiness reports with dependency, scope, cursor, and status evidence, but no secret values | Separates "mock tests pass" from "this account/integration is actually ready" |
| Confirmation flow | Require explicit confirmation before sending emails, submitting forms, uploading files, syncing calendar events, deleting data, or changing sharing permissions | These actions create external side effects |
| Durable approvals | Record who approved an external write, what object was written, what evidence supported it, and the confirmation ID used | Makes side effects reviewable and prevents silent replay |
| Calendar safety | Draft by default; dedupe before create; update by stable event ID; keep evidence link; never silently delete user-created events | Avoids duplicate or incorrect deadline events |
| Source trust labels | Label facts as email-derived, attachment-derived, portal-verified, user-provided, RAG-derived, or inferred | Makes answer confidence auditable |
| Fail-loud uncertainty | If sources conflict or current state cannot be verified, answer `uncertain` and recommend the safer earlier deadline when appropriate | Prevents false confidence on high-risk personal tasks |
| PII redaction | Redact emails, phones, addresses, IDs, exact portal URLs, file paths, account numbers, and calendar invitees in share packages, then run `privacy audit` before sharing | Keeps public demos and exported reports private |
| Local-first storage | Keep raw emails, attachments, screenshots, evidence, and calendar drafts local by default | Reduces exposure from cloud storage and model providers |
| RAG safety | Treat retrieved emails, webpages, PDFs, and portal content as untrusted data; ignore instructions inside retrieved content | Prevents prompt injection from documents or webpages |
| Tool allowlist | Tools must be registered with capability metadata, allowed side effects, required confirmation, and audit logging | Makes LangChain/LangGraph orchestration controllable |
| Model privacy | Default to local models when possible; cloud model use must be configurable and visible | Avoids leaking sensitive life-admin content by default |
| Audit trail | Log every scan, extraction, retrieval, tool call, draft event, calendar sync, and user confirmation | Supports debugging and user trust |
| Data retention | Let users purge raw artifacts, old evidence, attachments, and calendar drafts by source or date range | Personal admin data should not accumulate indefinitely |
| Background sync limits | Rate-limit mailbox/portal/calendar checks and avoid form submission or high-frequency scraping by default | Reduces account-lock, anti-bot, and accidental automation risk |
| Sandbox-first integrations | Exercise Gmail and calendar behavior against fake or sandbox clients before any real account write path | Keeps development and demos away from personal production data |
| Write replay protection | Bind each confirmed write to one confirmation ID and reject reuse | Prevents repeated calendar writes from a stale UI or retried request |
| High-stakes domain guard | For immigration, legal, financial, school, and housing deadlines, cite evidence and tell the user when an official source still needs manual verification | Avoids overclaiming authority in domains where mistakes are costly |

## Safety Verification Matrix

| Safety Claim | Current Evidence | Remaining Verification |
| --- | --- | --- |
| No external writes without confirmation | Calendar sync planner, dashboard ICS confirmation, CLI Google/Apple sync confirmation gates, fake Google/Apple adapter tests, sandbox Google/Apple verification, audit logs for blocked/confirmed writes, durable `approval_records`, approval replay protection, `sentineldesk approvals list`, `/api/approvals`, and dashboard approval history | Run the same boundary against live Google and Apple Calendar clients |
| No secrets persisted | `SecretRef`, env-only Google/Apple configs, redacted secret status, redacted credential/token format checks, redacted token scope checks, redacted Apple Calendar username/app-password format checks, `integrations env-template`, `integrations google-token` redacted metadata and 0600 token-output files, live verification reports that show `env:NAME:***` only, real Google OAuth token generation without printing token JSON, and clean redacted-output privacy audit after Gmail-first verification | Recheck persisted reports after any new connector type; Apple app-password evidence remains optional/later |
| Latest facts are tool-verified | `ask` routes deadline/amount questions through email search, returns `uncertain` on conflicts, can execute bound `capture_latest_portal` for page-change questions, falls back from email to portal capture when email says to log in or view the portal for a deadline, and real Gmail readonly sync produced a persisted cursor plus local deadline evidence from the live mailbox | Add live portal fallback evidence only when a Gmail result points to a portal but withholds the deadline |
| RAG cannot override tools | RAG is scoped to explanation and local/trusted docs; alert decisions remain deterministic; policy questions in `ask` call `search_policy_docs` and return citations; prompt-injection sanitization, trust-weighted retrieval evals, verified-deadline override resistance, write-tool trigger resistance, and installed LangGraph workflow readiness are covered | Re-run the same boundary through live connector paths |
| Share packages are redacted | Redacted evidence JSON/HTML/ZIP packages and integration verification ZIP packages remove local paths, sensitive identifiers, email headers, attachment names, calendar invitees, secret-bearing fields, and connector cursor/account metadata; `privacy audit --require-clean` scans redacted outputs without echoing raw leaked values; `privacy release-audit --require-clean` scans the project tree for local runtime artifacts; `privacy release-package` writes a clean source ZIP excluding those artifacts; Gmail-first package `20260611T130933+0000-gmail.share.zip` passed redacted-output privacy audit | Recheck redaction behavior after any new real source type, then package with release-package before sharing |
| Integrations are readiness-checked | `integrations env-template`, `integrations google-token`, `integrations handoff`, `integrations package`, `integrations check --package`, `integrations check/reports`, `integrations check --suite sandbox`, installed `integrations check --suite langgraph --require-ready`, installed Gmail OAuth flow, Gmail/Google Calendar/Apple Calendar connector-module readiness, redacted Google credential/token format validation, redacted Apple Calendar username/app-password format validation, `calendar sync --destination google/apple` confirmation gates, non-sandbox calendar sync-evidence checks, structured `completion-audit.readiness_action_plan`, `source_release_audit` completion requirement, Markdown handoff checklist with side-effect labels, `integration_verifications`, `/api/integrations/verifications`, dashboard count, `docs/LIVE_VERIFICATION.md`, optional `gmail`/`calendar`/`integrations` dependency extras, module-entrypoint exit-code coverage so `--require-ready` fails shell/CI when readiness is missing, and `integrations check --suite gmail --require-ready --package` ready evidence from a real readonly Gmail sync | Calendar all-suite readiness is deferred; if Calendar becomes useful, add non-sandbox Google/Apple approval records and rerun all-suite/completion audit |
| Approval history is retainable | `retention purge --source approvals`, `/api/retention/purge`, and dashboard retention controls preview counts first and delete old local records only after confirmation | Recheck retention/redaction behavior after real Gmail and calendar data are ingested |
| Calendar deadlines are visible by date | `/api/calendar/events` and the dashboard month/week/day board show email-derived deadlines on their normalized dates with source trust, draft/synced status, uncertainty markers, local date edits, and evidence-backed ICS confirmation | Add richer reminder/timezone controls after live calendar connector checks |

## Removed Old Plan Scope

The following JobOps Guard scope is no longer the active plan:

- generic job portal watcher as the main product
- JD-vs-resume review as a core feature
- Greenhouse/Lever/Workday broad fixture set
- form-filling assistant as a first-class module
- root React/Vite dashboard shell
- root `jobops` CLI/package

Job-specific demo fixtures are removed from SentinelDesk. The active demo should focus on email-derived lease/rent/billing deadline flows with calendar reminders. OPT/appointment fixtures can remain as synthetic reliability examples, but they are not the main product pitch.

## Verification Commands

Run from the active project:

```bash
cd sentinel-desk
python3 -B -m unittest discover -s tests -v
```

Current expected result: 191 tests pass.

Current Gmail-first live checkpoint:

```bash
cd sentinel-desk
export SENTINEL_GOOGLE_CREDENTIALS_JSON="$(cat .demo/secrets/google-client.json)"
export SENTINEL_GOOGLE_TOKEN_JSON="$(cat .demo/secrets/google-token.json)"
.agent-venv/bin/python -B -m sentineldesk --home .demo email sync-gmail --account user@example.com --query "deadline OR due" --credentials-env SENTINEL_GOOGLE_CREDENTIALS_JSON --token-env SENTINEL_GOOGLE_TOKEN_JSON
.agent-venv/bin/python -B -m sentineldesk --home .demo integrations check --suite gmail --account user@example.com --google-credentials-env SENTINEL_GOOGLE_CREDENTIALS_JSON --google-token-env SENTINEL_GOOGLE_TOKEN_JSON --require-ready --package
.agent-venv/bin/python -B -m sentineldesk --home .demo privacy audit --require-clean
```

Calendar live writes are not part of the current Gmail-first completion gate. Keep them deferred unless the product workflow needs confirmed external calendar sync.

Optional LangGraph dependency-path check:

```bash
cd sentinel-desk
python3 -B -m venv .agent-venv
.agent-venv/bin/python -m pip install -e '.[agent]'
.agent-venv/bin/python -B -m sentineldesk --home .demo integrations check --suite langgraph --require-ready
```

Optional local demo:

```bash
cd sentinel-desk
python3 -m sentineldesk --home .demo init
python3 -m sentineldesk --home .demo demo seed
python3 -m sentineldesk --home .demo demo scenarios
python3 -m sentineldesk --home .demo watch run
python3 -m sentineldesk --home .demo demo apply opt_action_required --run
python3 -m sentineldesk --home .demo demo apply lease_notice_required --run
python3 -m sentineldesk plan status
python3 -m sentineldesk --home .demo serve --port 8787
```

## Release Criteria For Interview Portfolio

- One clean vertical demo with baseline, meaningful change, and fail-loud uncertainty states.
- Evidence bundle visible in dashboard.
- Tests show that session expired, captcha, portal redesign, deadline change, and irrelevant copy changes are classified correctly.
- Public repo has no real portal URLs, cookies, screenshots, DOM dumps, or local databases.
- Redacted HTML report can be opened without exposing target URLs or personal identifiers.
- Interview package includes a concise architecture diagram and timed demo script.

## Release Criteria For Agent Assistant Extension

- `sentineldesk ask` can answer at least:
  - latest deadline questions
  - latest alert explanation questions
  - status meaning questions
  - next-step recommendation questions
- Deadline and latest-message answers must run a live capture or explicitly state that current state could not be verified.
- RAG answers must include source citations from local evidence, trusted docs, or imported user docs.
- The assistant must never downgrade an `uncertain` portal state into a confident answer.
- Model provider can be switched through config without changing tool code.
- Assistant routing and uncertainty behavior are covered by tests.
