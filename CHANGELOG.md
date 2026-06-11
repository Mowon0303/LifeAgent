# Changelog

All notable project updates for LifeAgent are tracked here.

## [Unreleased]

### Added

- Added conservative relative-deadline extraction to `extract_deadlines`: `within N days`, `at least N business days before the ... date`, user-action `N-day grace period` windows, `next Friday`-style weekdays, and `by the end of the month`; added targeted tests proving positive extraction and skipping no-action refund/deposit processing windows.
- Added expanded date-form extraction for day-month-year (`14 July 2026`), month-day without year (`June 5`), and ISO datetime `T` suffixes (`2026-07-12T22:00` -> `2026-07-12`), with tests proving full month dates are not split into shorter duplicates.
- Added non-dollar and malformed amount extraction: common currency symbols (`€`, `£`, `¥`, `￥`), ISO-style prefixes (`USD`, `EUR`, `GBP`, `CNY`, `RMB`), single-decimal amounts such as `$47.5`, and zero-width separator cleanup for obfuscated numeric strings such as `$1\u200b,250`.
- Added context-gated spelled-out amount extraction for dollar/USD phrases such as `one thousand two hundred dollars`, with tests proving lease-deposit extraction and filtering of marketing noise such as `Save two dollars`.
- Added high-confidence numeric amount false-positive filters for prompt-injected payment instructions, completed payment receipts, balance-transfer promo `$0` fees, low-balance thresholds, `$0.00` fine balances, and EOB `Amount billed` / `Plan paid` lines; targeted tests preserve true `You may owe` and failed-payment amounts.
- Added low-confidence numeric amount false-positive filters for refund/reimbursement, credit-applied, order receipt total, referral bonus, dental special, hotel room-price, and premium-upgrade marketing contexts; targeted tests preserve real low-confidence obligations such as price changes, annual fees, and suspicious charges.
- Added semantic amount/source-trust filters for informational credit-limit increases and lookalike-sender phishing payment requests; targeted tests preserve real processing fees, housing deposits, and minimum payments.
- Added expanded life-admin action extraction for `contact`, `register`, `apply`, `dispute`, `redeem`, `update`, `cancel`, `verify`, `reply`, `bring`, `report`, `check`, `add`, `print`, `enroll`, and `contest`, with targeted tests for the expanded lexicon and known noise patterns.
- Added `docs/PIVOT_POSTMORTEM.md`, a blameless postmortem of the two 36-hour product pivots (JobOps Guard → SentinelDesk → email-first LifeAgent): per-pivot what-broke/why/detection, the shared capability-first root cause, what survived, a prevention table mapping each new project mechanism to the failure it blocks, cost accounting, and portable lessons. Linked from the root README.
- Added `stored_email_messages` so the assistant can rebuild EmailMessage evidence from persisted local mail; CLI `ask` (without `--email-json`) and dashboard `/api/ask` now answer over the most recent 200 stored messages, cited as `stored_email:<id>`.
- Added contract tests proving the stored-evidence path: four conflicting stored deadlines answer `uncertain` with the safer earlier candidate and `stored_email:` citations, and a single stored deadline reaches a confident verified answer through the dashboard endpoint.

- Added `sentineldesk/agent/llm.py`: a stdlib `OllamaChatClient` plus a guard-railed `refine_answer` stage so a user-approved local model can rephrase verified assistant answers. Hard boundaries: uncertain answers and confirmation boundaries are never sent to the model; every date/amount anchor in the deterministic answer must survive the rewrite; model-introduced dates/amounts are rejected; errors/timeouts/overlong rewrites fall back silently to the deterministic text; the original text is preserved in `metadata.deterministic_answer`.
- Added a `refine` workflow stage to `answer_with_workflow` with `metadata.model_call` exposure and `workflow_trace` coverage; CLI `ask` and dashboard `/api/ask` pass `paths` so every model call is attributed.
- Added the `model_calls` table for per-call cost/latency attribution (provider, model, stage, intent, status, prompt/completion tokens, duration; question and answer text are never persisted), with `sentineldesk model calls` and `GET /api/model/calls` returning totals, per-status counts, and per-model aggregates.
- Added `tests/test_model_loop.py` with 11 cases covering fact-anchor extraction, successful rewrite with token recording, anchor-loss fallback, invented-fact fallback, model-error fallback, uncertain/confirmation skip boundaries, local-provider no-op, workflow persistence, and attribution summaries.

- Added `sentineldesk/static/calendar.html`, served at `/calendar`: the Calendar + AI assistant page implemented from the user-provided design package (`design_handoff_calendar_ai/`, selected direction B′). Warm-paper Bento month grid, week/day time grids with a live now-line, agenda view with relative dates and a trailing undated group, and a Discord-style assistant panel with summary embed, pending-suggestion cards, confirmation-gated "确认加入日历" (local ICS export with single-use confirmation IDs), "忽略" (task review `ignored`), and a composer wired to `/api/ask` with uncertainty styling and citation chips. No build step and no external script dependencies.
- Added `POST /api/ask` to the dashboard server, exposing the assistant workflow to the UI with the same answer shape as CLI `ask` (intent, answer, confidence, uncertain, requires_confirmation, tool_calls, citations, metadata).
- Added `docs/UI_CONTRACT.md`, the stable backend↔UI handoff contract: documented response shapes for calendar events, tasks, task review, calendar sync, draft update, and ask, plus design-mapping rules (pending=dashed/`approval_state: draft`, confirmed=solid/`approved`, source-trust captions, undated-deadline placement, confirm/ignore semantics).
- Added `fixtures/ui/` with synthetic sample emails and committed sample API responses (`calendar_events.sample.json`, `tasks.sample.json`, `ask_answer.sample.json`).
- Added `tests/test_ui_contract.py` with 17 regression gates: calendar item and task field shapes, confirm flow turning `draft` into `approved`, confirmation-ID replay blocking, ignore review flow, ask answer/citation payload shapes, fixture-vs-live shape sync, synthetic-fixture guard, and `/calendar` page wiring (including a no-external-scripts assertion).
- Added proper static content types (`.css`, `.js`, `.json`, `.svg`) to the dashboard server.

- Added `sentinel-desk/evals/golden/` with 142 hand-labeled synthetic email cases across 10 categories (lease/rent, billing/utility, bank/card, immigration/school, subscriptions, insurance/medical, tax/government, edge cases, negatives, adversarial), including marketing/receipt/injection false-positive traps, relative-deadline and non-dollar-currency recall gaps, attachment-only and subject-only facts, zero-width obfuscation, and a 10-date stuffing attack against the extraction cap.
- Added `evals/golden/README.md` documenting the semantic ground-truth labeling policy (which dates/amounts/actions count as life-admin obligations and which are deliberate traps or out-of-scope domains).
- Added `sentineldesk/evals/email_extract.py`, a golden-set eval harness that scores field-level precision/recall/F1 for deadline/amount/action extraction on raw and high-confidence layers, computes confidence-bucket calibration, and renders text, JSON, and Markdown reports.
- Added `sentineldesk eval email-extract --golden ... --report-md ... --json` CLI command and the generated committed report `docs/EVAL_REPORT.md`.
- Added `tests/test_eval_email_extract.py` with 9 regression gates: golden-set integrity (size, categories, unique IDs, `.example` senders), raw and high-confidence metric floors set just below the measured baseline, risk-word calibration direction (high bucket must not fall below low bucket precision), action flat-confidence structure, suppression-injection resistance (`adv-010` real facts must survive), and negative-category purity.

- Added `sentineldesk/email/` with local email message models, message search, and deadline/amount/action extraction from message and attachment text.
- Added `sentineldesk/email/ingest.py` and `sentineldesk email scan --json ...` for local email JSON ingestion into persisted evidence.
- Added email connector abstractions with local JSON and authenticated-client Gmail adapter boundaries.
- Added `email sync-gmail` with Google OAuth secret references, Gmail readonly scope declaration, stored incremental connector cursor support, and connector state inspection through `connectors state`.
- Added local attachment parsing for text, HTML, and optional PDF parser-backed attachments.
- Added `email_messages` persistence with extracted deadline/amount/action facts and `/api/email/facts` for read-only dashboard access.
- Added `sentineldesk/calendar/` with deadline event models, reminder rules, draft generation, dedupe/update planning, confirmation-gated sync planning, and ICS export.
- Added persisted `calendar_drafts`, `/api/calendar/drafts`, and a dashboard calendar draft preview fed by email-derived deadlines.
- Added `sentineldesk/calendar/view.py` and `/api/calendar/events` to normalize draft dates, merge approval/sync state, and expose source-trust metadata for calendar rendering.
- Added dashboard Month/Week/Day calendar views with dated deadline chips, draft/synced state, source trust, uncertainty styling, evidence tooltips, and confirmation-gated ICS export.
- Added confirmation-gated calendar adapter sync with ICS file output and Google Calendar client boundary.
- Added Apple Calendar/CalDAV authenticated-client boundary behind the same confirmation-gated calendar adapter flow.
- Added remote calendar upsert behavior for Google/Apple adapters: list existing events, update matching LifeAgent events, create only missing events, and audit created/updated external IDs.
- Added `sentineldesk/agent/` with intent routing, tool registry, optional LangChain/LangGraph availability detection, retrieval skeleton, and graph-style `answer_question`.
- Added `sentineldesk/agent/workflow.py` so `ask` can use an optional route/tools/finalize LangGraph workflow path when available and otherwise falls back to the same multi-stage rule workflow with runtime metadata.
- Added `sentineldesk/agent/providers.py` with local, Ollama, OpenAI, and Anthropic adapter boundaries, safe request-shape builders, redacted env-secret status, and `AgentAnswer` structured output validation.
- Added a reproducible project-local `.agent-venv` optional dependency path for exercising installed LangChain/LangGraph agent dependencies without changing the system Python environment.
- Added `gmail`, `calendar`, and `integrations` optional dependency extras for Google API, Google auth, and CalDAV live connector paths.
- Added `sentineldesk integrations env-template` to print live Gmail/Calendar env requirements, redacted availability status, install commands, verification commands, and sync commands without exposing secret values.
- Added `sentineldesk integrations google-token` to run the local Google OAuth browser flow and write authorized token JSON to a local 0600 file without printing token values.
- Added `sentineldesk calendar sync --destination ics|google|apple` so local calendar drafts can be previewed, then confirmation-gated into ICS, Google Calendar, or Apple Calendar from the CLI.
- Added `sentineldesk calendar edit`, `/api/calendar/drafts/update`, and dashboard `Save Date` controls so users can edit or reschedule local deadline drafts before external sync.
- Added `sentineldesk integrations package VERIFICATION_ID|latest` to export redacted integration verification ZIP packages for live readiness handoff.
- Added `sentineldesk integrations check --package` so a readiness check can persist its report and write the redacted ZIP package in one step.
- Added `docs/SECURITY_MODEL.md` to make trust boundaries, data classes, required controls, and the live verification standard explicit.
- Added `scripts/live_verification_preflight.sh` as a default-safe live Gmail/Calendar handoff script with dry-run mode, redacted package export, and explicit gates for Google OAuth, Gmail sync, and external calendar writes.
- Added final source release-package and release-audit execution to `scripts/live_verification_preflight.sh`, enabled by default through `SENTINEL_LIVE_RUN_RELEASE_PACKAGE=1` and disabled with `SENTINEL_LIVE_RUN_RELEASE_PACKAGE=0`.
- Added `sentineldesk integrations seed-calendar-draft` so live calendar sync verification can create a local sandbox deadline draft without depending on Gmail search results.
- Added `sentineldesk integrations completion-audit` so final live verification requires both current all-suite readiness and a persisted ready redacted package.
- Added a structured `completion-audit.readiness_action_plan` that maps missing live checks to concrete commands, side-effect labels, and user-approval requirements.
- Added `source_release_audit` as a machine-checked `completion-audit` requirement, with `--source-release-path` support and redacted private-path handling in action-plan commands.
- Added `sentineldesk integrations handoff` to render the completion audit and readiness action plan as a human Markdown checklist with side-effect labels, user-approval flags, final source release audit commands, and no secret values.
- Added redacted Google OAuth credentials/token format checks (`*.credentials_format`, `*.token_format`) so readiness reports distinguish missing env refs, malformed JSON/base64 JSON, missing token/client fields, and missing OAuth scopes without exposing secret values.
- Added redacted Apple Calendar username/app-password format checks so CalDAV readiness distinguishes missing env refs, malformed Apple ID/app-specific password inputs, and real external sync evidence without exposing secret values.
- Added `sentineldesk privacy audit` to scan redacted JSON/HTML reports and `.share.zip` packages for unredacted emails, phone numbers, local paths, URLs, and secret-like JSON values without echoing raw leaked values.
- Added `sentineldesk privacy release-audit` to scan the project tree for local runtime artifacts, generated caches, databases, screenshots, recordings, share packages, virtualenvs, and build metadata before public release.
- Added `sentineldesk privacy release-package` to write a public source ZIP while excluding the same local artifacts flagged by `privacy release-audit`.
- Added redacted Google OAuth token scope checks so Gmail readiness requires `gmail.readonly` and Google Calendar readiness requires `calendar.events` without exposing token values.
- Added a bound `capture_latest_portal` tool handler so page-change questions can call the deterministic monitor core from the assistant/CLI path.
- Added config-driven model provider loading from `[model]` and `sentineldesk model status`.
- Added persistent local RAG indexing in SQLite with `sentineldesk rag index/search/docs`.
- Added trust-weighted sparse lexical RAG ranking with score, matched terms, trust weight, document source, title, token count, and chunk metadata in retrieval results.
- Added `rag index --title` and repeated `--metadata key=value` for richer trusted-doc indexing.
- Added `search_policy_docs` as a local RAG-backed agent tool, so `ask` can answer policy/rule questions with citations from indexed documents.
- Added RAG prompt-injection detection and sanitization for untrusted retrieved documents.
- Added `audit_events`, `/api/audit/events`, dashboard audit count, and `sentineldesk audit list`.
- Added `approval_records`, `/api/approvals`, dashboard approval count/history preview, and `sentineldesk approvals list` for durable confirmation history.
- Added `connector_states`, `/api/connectors/state`, dashboard connector count, and env-only secret references with redacted summaries.
- Added `integration_verifications`, redacted external-integration readiness reports, `sentineldesk integrations check/reports`, and `/api/integrations/verifications`.
- Added `sentineldesk integrations check --suite sandbox` to exercise Gmail connector sync, Google/Apple calendar confirmation gates, approval records, audit logs, and redacted integration reports without external credentials.
- Added `sentineldesk/tasks.py`, `task_reviews`, `sentineldesk tasks list/review`, `/api/tasks`, and `/api/tasks/review` so extracted Gmail facts and local calendar drafts become reviewable work items before the UI design is implemented.
- Added dashboard integration verification count so local UI shows whether live/sandbox checks have been run.
- Added `docs/LIVE_VERIFICATION.md` with Gmail OAuth, Google/Apple Calendar, LangGraph, and redacted report commands.
- Added confirmation-gated local retention purge controls through `sentineldesk retention purge`.
- Added `/api/retention/purge` and dashboard retention controls for preview-first local data cleanup with confirmation-gated deletion.
- Added `/api/rag/docs` and `/api/rag/search` for read-only RAG dashboard/API access.
- Added `/api/calendar/sync` and dashboard `Export ICS` confirmation for local calendar draft export.
- Added source conflict detection for assistant answers so conflicting deadline/amount evidence returns `uncertain`; deadline conflicts include the safer earlier candidate.
- Added stored cross-source conflict detection across email facts, calendar drafts, and portal run evidence, with earliest-deadline safety selection.
- Added email-to-portal deadline fallback so deadline questions can run deterministic portal capture when available email says to log in or view the portal but does not expose the date.
- Added portal fallback citation chaining: answers now cite both the portal run evidence and the triggering email that said the user must log in or view the portal.
- Added `sentineldesk ask "..." --email-json ...` for offline email-first question answering with citations and uncertainty behavior.
- Added evidence-backed `ask` answers for latest alert explanation, status meaning, and next-step recommendation using the local `read_evidence_bundle` tool over the latest stored run.
- Added tests for email extraction, email scan persistence, calendar draft APIs, calendar confirmation safety, durable approval records, tool registry write blocking, connector trust labels, sandbox/live verification reports, audit logging, retention gates, RAG injection filtering, retrieved-instruction resistance for verified deadlines and calendar write tools, assistant routing, forced email search for deadline questions, email-to-portal deadline fallback, and CLI ask.
- Added eval coverage for email-to-portal fallback citations, uncertain session-expired fallback results, CLI `ask` fallback output, and workflow metadata that records runtime fallback tool calls.
- Added CLI/API tests proving local calendar draft edits reset previously synced drafts back to `draft`/`local_draft`, audit `calendar.edit`, and do not create external approval records.
- Added lease/rent synthetic vertical with current, written-notice-required, and rent-due scenarios.
- Added CDP screenshot artifact capture for Chrome DevTools runs, with screenshot paths recorded in raw evidence metadata.
- Added `/api/package/<run_id>` and a dashboard `Download Package` link for redacted evidence ZIP downloads.
- Added `evidence RUN_ID --package` to create a redacted shareable ZIP package with README, manifest, JSON evidence, and HTML report.
- Added dashboard smoke tests for scenario apply+run, redacted evidence, and HTML report routes without binding a local port.
- Added agent tests proving page-change questions execute the bound portal capture tool and persist monitor evidence.
- Added Chrome launcher tests covering dedicated profile startup and default-profile refusal.
- Added `docs/RECORDING_CHECKLIST.md` for the final portfolio demo recording pass.
- Added `demo record-prep` to generate the complete manual-recording state, run IDs, reports, and share packages in one command.
- Added `scripts/record_portfolio_demo.sh` to prepare the demo, start the dashboard, open the browser, and invoke macOS screen recording.
- Added an explicit recording approval guard plus `SENTINEL_RECORD_DRY_RUN=1` setup verification for the recording helper.
- Added interview-ready architecture documentation and a timed demo video script.
- Added `plan status` so plan-tracker responses always show completed plans and the next plan to complete.
- Added optional `cdp://` Chrome DevTools capture under the SentinelDesk package while keeping file fixtures as the public demo path.
- Added OPT/USCIS/OIS as the first vertical pack, with appointment slots as the secondary demo.
- Added scenario transitions for baseline, action required, approved, appointment available, session expired, captcha, maintenance, and portal redesign.
- Added redacted JSON evidence and redacted HTML reports for evidence bundles.
- Added structured redaction tests for email headers, attachment names, calendar invitees, secret fields, and connector metadata in redacted share packages.
- Added dashboard controls for applying scenarios, running one target, toggling redacted evidence, and opening reports.

### Fixed

- Filtered expanded-action false positives from email local parts such as `reply@...` / `no-reply@...`, noun-like `update/check/report` contexts, `Terms apply`, app-store update prompts, and conditional security-support prompts.
- Fixed the remaining amount false negative in the current golden set: `one thousand two hundred dollars` is now extracted without adding raw amount false positives.
- Fixed 9 high-confidence amount false positives in the current golden set while keeping amount recall at 1.000.
- Fixed 10 low-confidence amount false positives in the current golden set while keeping amount recall at 1.000.
- Fixed the final 2 raw amount false positives in the current golden set while keeping amount recall at 1.000.
- Fixed the assistant panel showing stale confirmed/pending counts after confirm/ignore actions (user-reported and user-fixed): the summary embed now carries `id="aiSummary"`, and `refresh()` recomputes both the embed and the channel-topic counter through `updateSummary()`, so the numbers update immediately without a page reload. Browser-verified (confirm flipped the summary from 1 confirmed / 3 pending to 2 / 2 in place) and locked by a page-wiring regression test.
- Fixed the root README still claiming 217 expected tests (user-reported); the count now tracks the current suite.

### Changed

- Raised the email-extraction eval gates after the relative-deadline improvement: raw deadline floors are now P>=0.74/R>=0.92 and high-confidence deadline floors are now P>=0.83/R>=0.51.
- Raised the email-extraction eval gates after date-form expansion: raw deadline floors are now P>=0.75/R>=0.96 and high-confidence deadline floors are now P>=0.84/R>=0.55.
- Raised the email-extraction eval gates after the non-dollar amount improvement: raw amount floors are now P>=0.77/R>=0.97 and high-confidence amount floors are now P>=0.79/R>=0.52.
- Raised the email-extraction eval gates after spelled-out amount extraction: raw amount floors are now P>=0.78/R>=0.99 and high-confidence amount floors are now P>=0.80/R>=0.54.
- Raised the email-extraction eval gates after high-confidence amount false-positive filtering: raw amount floors are now P>=0.85/R>=0.99 and high-confidence amount floors are now P>=0.96/R>=0.54.
- Raised the email-extraction eval gates after low-confidence amount false-positive filtering: raw amount floors are now P>=0.96/R>=0.99 while the high-confidence amount floor remains P>=0.96/R>=0.54.
- Raised the email-extraction eval gates after semantic amount/source-trust filtering: raw amount floors are now P>=0.99/R>=0.99 and high-confidence amount floors are now P>=0.99/R>=0.54.
- Raised the email-extraction eval gates after action-lexicon expansion: raw action floors are now P>=0.87/R>=0.98.
- Default `[model]` config now ships `provider = "local"` (deterministic rule path); enabling the local Ollama refinement path is an explicit opt-in via `config.toml`, keeping fresh homes and test environments from issuing model calls.
- Promoted the calendar assistant page to the main dashboard entry after user acceptance: `/` now serves `calendar.html` (with `/calendar` kept as an alias), the legacy monitor ops dashboard moved to `/ops`, the assistant panel header gained an ops-dashboard link, `demo record-prep` prints the `/ops` dashboard URL, and the recording docs point at `/ops`.
- Reframed the next product direction from portal-first monitoring to email-first LifeAgent: email and attachments are primary sources, portal/CDP capture becomes a verification tool, and calendar becomes the action layer.
- Added the planned calendar workflow: verified deadlines become draft events, reminders, dashboard calendar entries, and optional external calendar sync after confirmation.
- Expanded the calendar plan from simple export into a date-based product surface with evidence-linked deadline chips, draft/synced state, uncertainty markers, and reminder policy.
- Calendar visual system moved from plan to implementation: dashboard deadlines now render on their actual calendar dates instead of only in a flat draft list.
- Added safety as a first-class planning area covering permission scopes, confirmation flows, calendar write safety, source trust labels, RAG prompt-injection defenses, model privacy, audit trails, and data retention.
- Expanded the safety plan with background sync limits, sandbox-first integrations, write replay protection, and high-stakes domain guards.
- Expanded the safety plan into a verification matrix covering external-write confirmation, OAuth scope control, secret handling, live verification artifacts, tool-verified latest facts, RAG/tool boundaries, redacted share packages, and readiness checks.
- Calendar sync confirmations now write durable approval records with actor, action, capability, side effect, evidence refs, metadata, confirmation ID, and consumption timestamp.
- Calendar sync now blocks reused confirmation IDs before a second write can occur.
- Calendar remote sync now dedupes before create when the authenticated client exposes `list_events`/`update_event`, reducing duplicate deadline-event risk.
- Dashboard approval history now shows recent confirmed actions without rendering approval metadata payloads.
- Retention purge now supports `approvals` as a confirm-gated source so approval history does not accumulate forever, and the dashboard exposes the same preview-before-delete safety boundary.
- Assistant workflow metadata now includes route/tools/finalize trace events and planned tools for both the rule workflow and the optional LangGraph-shaped path.
- Assistant workflow metadata now preserves `planned_tools_initial` and merges runtime fallback tool calls into `planned_tools`, so email-first routes still show when they escalated to portal capture.
- Assistant routing now distinguishes status-meaning and next-step questions from generic policy retrieval, while keeping those answers grounded in local evidence citations.
- Assistant policy/rule questions now run local RAG retrieval before answering; deadline/amount questions still use tool-verified email/portal evidence first.
- `model status` now includes adapter status without exposing API keys; OpenAI/Anthropic report only env secret availability and redacted refs.
- Integration readiness now distinguishes local sandbox verification from real account readiness; sandbox can pass without credentials, while live Gmail/Calendar/LangGraph checks still require user-approved credentials or dependencies.
- `python -m sentineldesk` now preserves CLI return codes, so `integrations check --require-ready` fails shell/CI when readiness is missing.
- `pyproject.toml` package discovery now only includes `sentineldesk*`, preventing editable installs from treating fixture directories as unintended top-level packages.
- LangGraph readiness moved from planned to verified: installed optional agent dependencies expose `langgraph.graph`, build the route/tools/finalize workflow as a `CompiledStateGraph`, and pass `integrations check --suite langgraph --require-ready`.
- Live Google readiness now checks the local OAuth browser-flow dependency `google_auth_oauthlib.flow` in addition to Google API and credential modules.
- Live Google readiness now checks OAuth credential and token JSON shape separately from token scope checks, so malformed env values fail before Gmail sync or calendar writes are attempted.
- Current live verification target changed to Gmail-first: real Gmail readonly sync and redacted Gmail readiness package now define the active external-service milestone.
- Calendar live writes moved behind a later product decision because current useful information is coming from Gmail; calendar remains a local visibility/action layer until confirmed external sync becomes valuable.
- UI implementation is paused pending the user-provided design reference package; non-UI work continues on backend contracts, task review state, safety, and evals.
- Task review aggregation now deduplicates email deadline facts that are already represented by local calendar drafts, while preserving amount/action facts as separate reviewable tasks.
- Retention purge now supports `tasks` as a local review-state source in the same preview-before-delete flow.
- Calendar sync CLI requires explicit `--confirm` for all writes and a stable `--confirmation-id` for Google/Apple external calendar writes; Google defaults to `primary`, Apple defaults to `default`.
- Calendar draft edits now stay local-only: changing a date or severity reopens the draft as `local_draft`, writes an audit event, and leaves external calendar approval history untouched until the user confirms a new sync.
- Calendar readiness now requires non-sandbox Google/Apple calendar sync approval evidence, so live reports cannot pass from dependencies and secrets alone.
- Integration verification artifacts now include their own artifact path in the written JSON, and redacted integration packages remove local paths and secret values before sharing.
- Integration verification IDs now get a numeric suffix when repeated checks run in the same second, preventing package/preflight runs from failing on unique ID collisions.
- `integrations check --package` now rejects `--no-persist` before touching the default home directory, preventing accidental local state creation for an invalid argument combination.
- `completion-audit` now includes `redacted_output_privacy` and `source_release_audit` requirements, and live verification preflight runs source release-package/release-audit before `completion-audit`; when `SENTINEL_LIVE_REQUIRE_READY=1`, redacted-output privacy leaks or source-release audit failures become hard failures.
- `completion-audit` now explains remaining live-verification work as explicit gates: optional dependency install, Google OAuth setup, Apple CalDAV setup, Gmail readonly sync, local calendar draft prep, confirmed Google/Apple calendar sync, final redacted package, final privacy audit, and final source release audit.
- `integrations env-template`, `completion-audit.next_commands`, `integrations handoff`, and the live preflight script now include the final source release-package, ZIP extraction, and release-audit commands so the live handoff checklist covers both redacted integration artifacts and public source packaging.
- Public release privacy status now distinguishes redacted-output privacy from project-tree release hygiene; the reusable release audit currently flags local ignored development artifacts that must be deleted or excluded before packaging.
- Public release packaging can now use an exclusion path instead of deleting the local development environment: `privacy release-package` excludes `.agent-venv`, egg-info, caches, screenshots, databases, recordings, and share artifacts before writing the ZIP.
- Updated the next safety target from local boundaries to production OAuth integrations, real remote calendar clients, connector secret handling, and authenticated connector evals.
- Updated the plan to add a LangChain/LangGraph assistant layer while keeping SentinelDesk's deterministic monitoring core independent from LLM/RAG decisions.
- Defined tool-first verification for latest facts such as deadlines, latest messages, alert reasons, and portal state before the assistant answers.
- Defined RAG as an explanation and documentation layer over local evidence, trusted docs, user-provided docs, and historical runs rather than as the alerting mechanism.
- RAG search now prefers trusted policy documents over untrusted matching text while still preserving prompt-injection warnings and sanitized text.
- Demo seeding now creates OPT, appointment, and lease/rent targets.
- Chrome launcher now starts a detached dedicated profile with an explicit `about:blank` URL so the DevTools endpoint stays available after the CLI exits.
- Redaction now removes local filesystem paths from redacted evidence and share packages, and structured redacted exports replace sensitive attachment, invitee, secret, and connector metadata fields with explicit placeholders.
- Hardened CDP tab selection so multiple open Chrome pages require deterministic `url`, `title`, or `id` selectors.
- Moved fail-loud behavior behind vertical policies so OPT, appointment, lease, generic, and low-stakes targets can diverge without changing classifier code.
- Status extraction now prioritizes terminal states such as `approved` above generic `pending` copy.

### Verified

- `cd sentinel-desk && python3 -B -m unittest discover -s tests -q` passed with 255 tests after adding semantic amount/source-trust filters and raised amount precision gates.
- `cd sentinel-desk && python3 -B -m sentineldesk eval email-extract --golden evals/golden --report-md docs/EVAL_REPORT.md` measured the semantic amount/source-trust improvement: raw amount P=1.000/R=1.000/F1=1.000 (tp=76/fp=0/fn=0) and high-confidence amount P=1.000/R=0.553/F1=0.712 (tp=42/fp=0/fn=34); raw amount false positives fell from 2 to 0 and no amount false positives or false negatives remain in the current golden set.
- `cd sentinel-desk && python3 -m compileall -q sentineldesk tests` passed after the semantic amount/source-trust filter update.
- `cd sentinel-desk && python3 -B -m sentineldesk --home /private/tmp/lifeagent-semantic-amount-release-home privacy release-package --source . --output /private/tmp/lifeagent-semantic-amount-filters-20260611.release.zip` wrote a 118-file source release ZIP excluding 10 local runtime artifacts, and `privacy release-audit --require-clean` passed on the extracted package with 0 issues.
- `cd sentinel-desk && python3 -B -m unittest discover -s tests -q` passed with 253 tests after adding low-confidence amount false-positive filters and raised raw amount precision gates.
- `cd sentinel-desk && python3 -B -m sentineldesk eval email-extract --golden evals/golden --report-md docs/EVAL_REPORT.md` measured the low-confidence amount false-positive improvement: raw amount P=0.974/R=1.000/F1=0.987 (tp=76/fp=2/fn=0) and high-confidence amount P=0.977/R=0.553/F1=0.706 (tp=42/fp=1/fn=34); raw amount false positives fell from 12 to 2 and low-confidence amount false positives fell from 11 to 1.
- `cd sentinel-desk && python3 -m compileall -q sentineldesk tests` passed after the low-confidence amount false-positive filter update.
- `cd sentinel-desk && python3 -B -m sentineldesk --home /private/tmp/lifeagent-low-confidence-amount-fp-release-home privacy release-package --source . --output /private/tmp/lifeagent-low-confidence-amount-fp-20260611.release.zip` wrote a 118-file source release ZIP excluding 10 local runtime artifacts, and `privacy release-audit --require-clean` passed on the extracted package with 0 issues.
- `cd sentinel-desk && python3 -B -m unittest discover -s tests -q` passed with 249 tests after adding high-confidence amount false-positive filters and raised amount precision gates.
- `cd sentinel-desk && python3 -B -m sentineldesk eval email-extract --golden evals/golden --report-md docs/EVAL_REPORT.md` measured the high-confidence amount false-positive improvement: raw amount P=0.864/R=1.000/F1=0.927 (tp=76/fp=12/fn=0) and high-confidence amount P=0.977/R=0.553/F1=0.706 (tp=42/fp=1/fn=34); raw amount false positives fell from 21 to 12 and high-confidence amount false positives fell from 10 to 1.
- `cd sentinel-desk && python3 -m compileall -q sentineldesk tests` passed after the amount false-positive filter update.
- `cd sentinel-desk && python3 -B -m sentineldesk --home /private/tmp/lifeagent-amount-fp-release-home-v2 privacy release-package --source . --output /private/tmp/lifeagent-amount-fp-filters-v2-20260611.release.zip` wrote a 118-file source release ZIP excluding 10 local runtime artifacts, and `privacy release-audit --require-clean` passed on the extracted package with 0 issues.
- `cd sentinel-desk && python3 -B -m unittest discover -s tests -q` passed with 245 tests after adding spelled-out amount extraction and raised amount eval gates.
- `cd sentinel-desk && python3 -B -m sentineldesk eval email-extract --golden evals/golden --report-md docs/EVAL_REPORT.md` measured the spelled-out amount improvement: raw amount P=0.784/R=1.000/F1=0.879 (tp=76/fp=21/fn=0) and high-confidence amount P=0.808/R=0.553/F1=0.656, with no remaining amount false negatives in the current golden set.
- `cd sentinel-desk && python3 -m compileall -q sentineldesk tests` passed after the spelled-out amount extractor update.
- `cd sentinel-desk && python3 -B -m sentineldesk --home /private/tmp/lifeagent-spelled-release-home privacy release-package --source . --output /private/tmp/lifeagent-spelled-amounts-20260611.release.zip` wrote a 118-file source release ZIP excluding 10 local runtime artifacts, and `privacy release-audit --require-clean` passed on the extracted package with 0 issues.
- `cd sentinel-desk && python3 -B -m unittest discover -s tests -q` passed with 243 tests after adding date-form expansion and raised deadline eval gates.
- `cd sentinel-desk && python3 -B -m sentineldesk eval email-extract --golden evals/golden --report-md docs/EVAL_REPORT.md` measured the date-form improvement: raw deadline P=0.763/R=0.975/F1=0.856 (tp=119/fp=37/fn=3) and high-confidence deadline P=0.852/R=0.566/F1=0.680 without increasing deadline false positives.
- `cd sentinel-desk && python3 -m compileall -q sentineldesk tests` passed after the date-form extractor update.
- `cd sentinel-desk && python3 -B -m sentineldesk --home /private/tmp/lifeagent-date-release-home privacy release-package --source . --output /private/tmp/lifeagent-date-forms-20260611.release.zip` wrote a 118-file source release ZIP excluding 10 local runtime artifacts, and `privacy release-audit --require-clean` passed on the extracted package with 0 issues.
- `cd sentinel-desk && python3 -B -m unittest discover -s tests -q` passed with 239 tests after adding action-lexicon expansion, noise filters, and raised action eval gates.
- `cd sentinel-desk && python3 -B -m sentineldesk eval email-extract --golden evals/golden --report-md docs/EVAL_REPORT.md` measured the action improvement: raw action P=0.885/R=1.000/F1=0.939 (tp=85/fp=11/fn=0), up from P=0.875/R=0.805/F1=0.838.
- `cd sentinel-desk && python3 -m compileall -q sentineldesk tests` passed after the action extractor update.
- `cd sentinel-desk && python3 -B -m sentineldesk --home /private/tmp/lifeagent-action-release-home privacy release-package --source . --output /private/tmp/lifeagent-action-lexicon-20260611.release.zip` wrote a 118-file source release ZIP excluding 10 local runtime artifacts, and `privacy release-audit --require-clean` passed on the extracted package with 0 issues.
- `cd sentinel-desk && python3 -B -m unittest discover -s tests -q` passed with 237 tests after adding non-dollar amount extraction and raised eval gates.
- `cd sentinel-desk && python3 -B -m sentineldesk eval email-extract --golden evals/golden --report-md docs/EVAL_REPORT.md` measured the non-dollar amount improvement: raw amount P=0.781/R=0.987/F1=0.872 (tp=75/fp=21/fn=1) and high-confidence amount P=0.804/R=0.539/F1=0.646.
- `cd sentinel-desk && python3 -m compileall -q sentineldesk tests` passed after the non-dollar amount extractor update.
- `cd sentinel-desk && python3 -B -m sentineldesk --home /private/tmp/lifeagent-currency-release-home privacy release-package --source . --output /private/tmp/lifeagent-currency-amounts-20260611.release.zip` wrote a 118-file source release ZIP excluding 10 local runtime artifacts, and `privacy release-audit --require-clean` passed on the extracted package with 0 issues.
- `cd sentinel-desk && python3 -B -m unittest discover -s tests -q` passed with 235 tests after adding relative-deadline extraction and raised eval gates.
- `cd sentinel-desk && python3 -B -m sentineldesk eval email-extract --golden evals/golden --report-md docs/EVAL_REPORT.md` measured the relative-deadline improvement: raw deadline P=0.757/R=0.943/F1=0.839 (tp=115/fp=37/fn=7) and high-confidence deadline P=0.844/R=0.533/F1=0.653 without increasing deadline false positives.
- `cd sentinel-desk && python3 -m compileall -q sentineldesk tests` passed after the relative-deadline extractor update.
- `cd sentinel-desk && python3 -B -m sentineldesk --home /private/tmp/lifeagent-relative-release-home privacy release-package --source . --output /private/tmp/lifeagent-relative-deadlines-20260611.release.zip` wrote a 118-file source release ZIP excluding 10 local runtime artifacts, and `privacy release-audit --require-clean` passed on the extracted package with 0 issues.
- `cd sentinel-desk && python3 -B -m unittest discover -s tests` passed with 232 tests after wiring stored email evidence into `ask`.
- Browser verification on `/`: asking "What is my latest deadline?" over four stored sample emails rendered the fail-loud conflict answer (uncertain styling, safer earlier candidate) with four `stored_email:` citation chips — the first dashboard answers grounded in persisted local evidence.
- `cd sentinel-desk && python3 -B -m unittest discover -s tests` passed with 230 tests after adding the model-in-the-loop guardrail suite.
- Real user-approved local Ollama dry-run (`qwen2.5:7b`, server 0.15.2): an English latest-deadline question returned a natural rewrite that preserved the `07/01/2026` anchor (199 prompt + 22 completion tokens, 22.8s cold start); a Chinese question returned a Chinese rewrite preserving the same anchor (201+35 tokens, 4.2s warm); a four-way conflicting-deadline question stayed `uncertain` and skipped the model with 0 tokens; `sentineldesk model calls` reported the attribution summary (3 calls, 457 total tokens, refine success rate 0.67, per-status and per-model breakdowns).
- `cd sentinel-desk && python3 -B -m unittest discover -s tests` passed with 219 tests after the root-route swap, including new assertions that `/` serves the calendar page, `/ops` serves the legacy dashboard, and the assistant header links to `/ops`.
- Browser verification after the swap: `/` renders the calendar assistant with the previously confirmed 6/21 deadline still solid (state persisted), `/ops` serves the scenario/evidence dashboard, and `/calendar` still works as an alias.
- `cd sentinel-desk && python3 -B -m unittest discover -s tests` passed with 217 tests after adding the UI contract gates and the calendar page.
- Browser verification of `/calendar` against a seeded demo home: month view rendered the warm-paper grid with today outlined and a dashed pending chip; confirming the first suggestion flipped the 6/21 chip from dashed purple to solid terracotta after a real confirmation-gated ICS export; ignoring advanced the suggestion queue and recorded the review; week view rendered the time grid with the now-line in today's column; agenda view grouped events with relative dates, type chips, and source-trust captions; the composer round-tripped `/api/ask` and rendered a fail-loud uncertain answer with the uncertainty style.
- `cd sentinel-desk && python3 -B -m unittest discover -s tests` passed with 200 tests after adding the email-extraction golden-set eval gates.
- `cd sentinel-desk && python3 -B -m sentineldesk eval email-extract --golden evals/golden --report-md docs/EVAL_REPORT.md` measured the extraction baseline over 142 cases: raw deadline P=0.736/R=0.844/F1=0.786, raw amount P=0.755/R=0.934/F1=0.835, raw action P=0.875/R=0.805/F1=0.838; high-confidence layer deadline P=0.810, amount P=0.796; confidence calibration confirmed the risk-word heuristic beats the low bucket (deadline 0.810 vs 0.675, amount 0.796 vs 0.711); every false positive/negative in the report was audited against the labeling policy and matches a designed trap or known capability gap.
- `cd sentinel-desk && python3 -B -m sentineldesk privacy release-package --source . --output ...` wrote a 108-file source release ZIP that includes all `evals/golden` fixtures and the eval harness while still excluding 10 local runtime artifacts.
- `cd sentinel-desk && python3 -B -m unittest discover -s tests -q` passed with 191 tests after adding portal fallback citation chaining, uncertain portal-fallback coverage, CLI `ask` fallback assertions, workflow runtime-tool metadata coverage, task review backend/API coverage, Gmail-first integration readiness, privacy/release audit gates, RAG safety, and connector/calendar safety tests.
- `cd sentinel-desk && python3 -m compileall -q sentineldesk tests` passed after the portal fallback citation update.
- `cd sentinel-desk && python3 -B -m sentineldesk --home /private/tmp/lifeagent-fallback-release-home-v2 privacy release-package --source . --output /private/tmp/lifeagent-fallback-20260611-portal-citations-v2.release.zip` wrote a 93-file source release ZIP while excluding 9 local runtime artifacts including `.demo`, `.agent-venv`, egg-info, and caches.
- `cd sentinel-desk && python3 -B -m sentineldesk --home /private/tmp/lifeagent-fallback-release-home-v2 privacy release-audit --path /private/tmp/lifeagent-fallback-20260611-portal-citations-v2-extract --require-clean` passed with 93 scanned files and 0 issues.
- `cd sentinel-desk && .agent-venv/bin/python -B -m sentineldesk --home .demo privacy audit --require-clean` passed with 4 scanned redacted share packages and 0 issues.
- `cd sentinel-desk && python3 -B -m unittest tests.test_task_review -v` passed with 3 tests covering task aggregation, task review persistence/audit, and CLI `tasks list/review`.
- `cd sentinel-desk && python3 -B -m unittest tests.test_dashboard_smoke.DashboardSmokeTests.test_task_api_exposes_reviewable_tasks_and_status_updates -v` passed, proving `/api/tasks` and `/api/tasks/review` expose reviewable backend state for the future UI.
- `cd sentinel-desk && .agent-venv/bin/python -B -m sentineldesk --home .demo integrations google-token --credentials-env SENTINEL_GOOGLE_CREDENTIALS_JSON --token-env SENTINEL_GOOGLE_TOKEN_JSON` completed the user-approved Google OAuth browser flow and wrote `.demo/secrets/google-token.json` with owner-only permissions without printing token values.
- `cd sentinel-desk && .agent-venv/bin/python -B -m sentineldesk --home .demo email sync-gmail --account user@example.com --query "deadline OR due" --credentials-env SENTINEL_GOOGLE_CREDENTIALS_JSON --token-env SENTINEL_GOOGLE_TOKEN_JSON` completed a real Gmail readonly sync with 50 messages persisted, 2396 facts extracted, 184 local deadline drafts, and a saved connector cursor.
- `cd sentinel-desk && .agent-venv/bin/python -B -m sentineldesk --home .demo integrations check --suite gmail --account user@example.com --google-credentials-env SENTINEL_GOOGLE_CREDENTIALS_JSON --google-token-env SENTINEL_GOOGLE_TOKEN_JSON --require-ready --package` reported `status: ready` and wrote redacted package `.demo/artifacts/integrations/20260611T130933+0000-gmail.share.zip`.
- `cd sentinel-desk && .agent-venv/bin/python -B -m sentineldesk --home .demo privacy audit --require-clean` passed after Gmail-first verification with 4 scanned redacted share packages and 0 privacy issues.
- `cd sentinel-desk && python3 -B -m unittest tests.test_live_verification -v` passed with 24 tests after adding env-template, completion-audit next-command, human handoff checklist, malformed Google secret detection, expected OAuth shape checks, Apple Calendar credential format checks, completion-audit source release requirement checks, and live preflight coverage for the source release-package/release-audit gate.
- `cd sentinel-desk && env SENTINEL_TEST_BAD_GOOGLE_CREDS=not-json-client-secret SENTINEL_TEST_BAD_GOOGLE_TOKEN=not-json-token-secret python3 -B -m sentineldesk --home /private/tmp/lifeagent-format-check-home integrations check --suite all --account sandbox@example.com --google-credentials-env SENTINEL_TEST_BAD_GOOGLE_CREDS --google-token-env SENTINEL_TEST_BAD_GOOGLE_TOKEN --no-persist` reported `gmail.credentials_format`, `gmail.token_format`, `google_calendar.credentials_format`, and `google_calendar.token_format` as `invalid` while outputting only redacted env refs.
- `cd sentinel-desk && env SENTINEL_TEST_BAD_APPLE_USER="bad apple user" SENTINEL_TEST_BAD_APPLE_PASSWORD=short python3 -B -m sentineldesk --home /private/tmp/lifeagent-apple-format-check-home integrations check --suite calendar --account sandbox@example.com --apple-user-env SENTINEL_TEST_BAD_APPLE_USER --apple-password-env SENTINEL_TEST_BAD_APPLE_PASSWORD --no-persist` reported `apple_calendar.username_format` and `apple_calendar.app_password_format` as `invalid` while outputting only redacted env refs.
- `cd sentinel-desk && python3 -B -m sentineldesk --home /private/tmp/lifeagent-source-release-home privacy release-audit --path /private/tmp/lifeagent-sentineldesk-apple-format-extract --require-clean` passed with 91 scanned files and 0 issues after packaging the current source tree.
- `cd sentinel-desk && python3 -B -m sentineldesk --home /private/tmp/lifeagent-handoff-checklist-home integrations handoff --account sandbox@example.com --output /private/tmp/lifeagent-handoff-checklist.md` wrote a Markdown checklist with completion gates, `external_read`/`external_calendar_write` side-effect labels, approval flags, and final source release audit commands without printing secret values.
- `cd sentinel-desk && env SENTINEL_LIVE_HOME=/private/tmp/lifeagent-preflight-source-gate-home SENTINEL_LIVE_PYTHON=python3 SENTINEL_LIVE_ACCOUNT=sandbox@example.com SENTINEL_LIVE_RELEASE_OUTPUT=/private/tmp/lifeagent-preflight-source-gate/sentinel-desk.release.zip bash scripts/live_verification_preflight.sh` completed without real credentials or external writes after the source-release gate reorder; it wrote redacted integration packages, wrote and audited a clean source release package before `completion-audit`, and passed the final redacted-output `privacy audit`.
- `cd sentinel-desk && python3 -B -m sentineldesk --home /private/tmp/lifeagent-final-source-home privacy release-package --source . --output /private/tmp/lifeagent-final-sentineldesk.release.zip` wrote the current source release ZIP with 91 files and excluded 8 local runtime artifacts; `privacy release-audit --path /private/tmp/lifeagent-final-sentineldesk-extract --require-clean` then passed with 0 issues.
- `cd sentinel-desk && python3 -B -m sentineldesk --home /private/tmp/lifeagent-final-source-home integrations completion-audit --account sandbox@example.com --source-release-path /private/tmp/lifeagent-final-sentineldesk-extract` reported `source_release_audit` as `ready` while correctly leaving real Gmail/Calendar credentials, cursor, sync evidence, and final ready package requirements missing.
- `cd sentinel-desk && env SENTINEL_LIVE_HOME=/private/tmp/lifeagent-preflight-release-gate-home SENTINEL_LIVE_PYTHON=python3 SENTINEL_LIVE_ACCOUNT=sandbox@example.com SENTINEL_LIVE_RELEASE_OUTPUT=/private/tmp/lifeagent-preflight-release-gate/sentinel-desk.release.zip bash scripts/live_verification_preflight.sh` completed without real credentials or external writes, wrote two redacted integration packages, passed `privacy audit` over those packages, wrote a 91-file source release ZIP, and passed `privacy release-audit --require-clean` on the extracted source tree.
- `cd sentinel-desk && python3 -B -m sentineldesk privacy release-audit --path /Users/zuge/Mywork/LifeAgent/sentinel-desk` reported `artifacts_found` for local ignored development artifacts: `.agent-venv`, `sentineldesk.egg-info`, and Python `__pycache__/` directories. This is an expected local-dev finding and must be cleaned or excluded before public packaging.
- `cd sentinel-desk && python3 -B -m sentineldesk privacy release-package --source /Users/zuge/Mywork/LifeAgent/sentinel-desk --output /private/tmp/lifeagent-release-package.WTdJbi/sentinel-desk.release.zip` wrote a source ZIP with 91 files and excluded 8 local artifacts; after extraction, `privacy release-audit --require-clean` passed with 0 issues.
- Running dashboard smoke on `127.0.0.1:8797` verified the HTML exposed `Save Date`, `/api/calendar/drafts/update` updated a local draft from July 2 to July 3, `/api/calendar/events` returned `date_key: 2026-07-03`, and `/api/audit/events` recorded `calendar.edit` with `side_effect: local_db_write`.
- `cd sentinel-desk && python3 -m compileall -q sentineldesk tests` passed after the clean release-package update.
- `cd sentinel-desk && .agent-venv/bin/python -B -m sentineldesk --home /private/tmp/lifeagent-privacy-audit-preflight integrations completion-audit --account sandbox@example.com` reported `redacted_output_privacy` as `ready` while correctly leaving live Gmail/Calendar credentials, cursor, sync evidence, and final ready package requirements missing.
- `cd sentinel-desk && .agent-venv/bin/python -B -m sentineldesk --home /private/tmp/lifeagent-privacy-audit-preflight privacy audit --require-clean` passed with 4 scanned redacted share packages and 0 privacy issues.
- `cd sentinel-desk && .agent-venv/bin/python -B -m sentineldesk --home /private/tmp/lifeagent-langgraph-ready integrations check --suite langgraph --require-ready` passed with status `ready` for `langgraph.module` and `langgraph.runtime`.
- `cd sentinel-desk && .agent-venv/bin/python -B -c "from sentineldesk.agent.workflow import build_langgraph_workflow; graph=build_langgraph_workflow(); print(type(graph).__name__); print(graph is not None)"` printed `CompiledStateGraph` and `True`.
- `cd sentinel-desk && .agent-venv/bin/python -B -m unittest tests.test_agent_orchestration tests.test_live_verification -q` passed with 16 tests against the installed optional dependency environment.
- `cd sentinel-desk && .agent-venv/bin/python -B -m sentineldesk model status` reported `langchain_available: true`, `langgraph_available: true`, and redacted local adapter metadata.
- `cd sentinel-desk && .agent-venv/bin/python -m pip install -e '.[integrations]'` installed Google API, Google auth, and CalDAV connector dependencies in the project-local virtual environment.
- `cd sentinel-desk && .agent-venv/bin/python -B -m sentineldesk --home /private/tmp/lifeagent-final-preflight-deps integrations check --suite all --require-ready` failed as expected with `partial` status because user-approved Gmail/Calendar env secrets and a post-sync Gmail cursor are not configured yet; Gmail/Google Calendar modules, Apple CalDAV, and LangGraph checks were `ready`.
- `cd sentinel-desk && python3 -B -m sentineldesk integrations env-template --account sandbox@example.com` printed redacted env refs, install commands, verification commands, and sync commands without exposing secret values.
- `cd sentinel-desk && .agent-venv/bin/python -m pip install -e '.[agent,integrations]'` installed the Google OAuth browser-flow dependency `google-auth-oauthlib` in the project-local virtual environment.
- `cd sentinel-desk && .agent-venv/bin/python -B -c "import google_auth_oauthlib.flow; print('google_auth_oauthlib.flow ready')"` verified the Google OAuth token helper dependency.
- `cd sentinel-desk && .agent-venv/bin/python -B -m sentineldesk --home /private/tmp/lifeagent-final-preflight-oauth integrations check --suite all --require-ready` failed as expected with `partial` status because user-approved Gmail/Calendar env secrets and a post-sync Gmail cursor are not configured yet; Gmail OAuth flow, Gmail/Google Calendar modules, Apple CalDAV, and LangGraph checks were `ready`.
- Chrome dashboard smoke on `127.0.0.1:8795` verified the Month calendar board rendered a July 2, 2026 email-derived deadline chip with draft/local state and `email_evidence` source trust.
- Real Chrome CDP dry-run captured the synthetic OPT fixture through `cdp://127.0.0.1:9223`, produced health `ok`, status `submitted`, and wrote a screenshot artifact.
- Browser-driven dashboard smoke verified scenario selection, Apply + Run, redacted evidence, report opening, package link enablement, and stable package-link click behavior.
- Clean portfolio demo pass produced baseline, `critical`, and `uncertain` states, loaded the dashboard, and verified a redacted share package with no `file://` leak.
- Earlier manual public-release privacy audit evidence is superseded by the executable `privacy release-audit` gate; the current local development tree must be cleaned or packaged without ignored artifacts before sharing.
- `demo record-prep` produced 5 runs, 2 alerts, baseline/critical/uncertain states, report paths, and redacted package paths for recording handoff.
- Recording helper script passed shell syntax validation; actual screen recording remains user-operated because macOS screen/audio permissions are local user actions.
- Recording helper dry-run produced the expected demo state without recording, and unapproved non-interactive execution exits before capture.

### Planned

- Keep Gmail readonly as the current live source and add portal fallback evidence only when an email says the user must log in to see the official deadline.
- Defer live Google/Apple Calendar sync until Calendar becomes a useful product workflow; when resumed, use one seeded verification draft, explicit confirmation, and all-suite/completion audit.
- Attach Calendar readiness reports only after the deferred Calendar milestone is intentionally resumed.
- Add embedding/vector ranking, richer trusted-doc metadata, and retrieval evals.
- Add assistant evals for user-approved live connector routing and citations using the redacted Gmail-first package shape.
- Keep duplicate remote calendar-event and live calendar-confirmation safety tests deferred with the Calendar milestone.
- User-operated screen recording with local screen/audio permissions.

## [0.2.0] - 2026-06-10

### Changed

- Pivoted LifeAgent from the old horizontal JobOps Guard pitch to the newer SentinelDesk plan: a fail-loud local portal sentinel for high-stakes deadlines.
- Moved the active implementation into `sentinel-desk/`.
- Updated root documentation so the repository points at SentinelDesk instead of the deleted JobOps package.
- Kept the project focused on reliability engineering: session health, deterministic diffing, uncertainty escalation, and evidence bundles.

### Removed

- Removed the old root `jobops/` package.
- Removed the old React/Vite `frontend/` dashboard shell.
- Removed old Greenhouse/Lever/Workday job fixtures under `fixtures/synthetic_portal/`.
- Removed old root tests tied to JobOps Guard.
- Removed `lifeagent_jobops.egg-info/`, `.jobops/`, `.venv/`, `.pytest_cache/`, and `.ruff_cache/` runtime/build artifacts.
- Removed stale root `pyproject.toml` that declared the deleted `jobops` package.
- Removed remaining job-specific SentinelDesk demo fixtures and seed target.

### Verified

- `cd sentinel-desk && python3 -B -m unittest discover -s tests -v` passed with 35 tests after removing job-specific fixtures.
- Verified the latest code path still demonstrates both `critical` meaningful-change alerts and `uncertain` fail-loud alerts in SentinelDesk.

## [0.1.0] - 2026-06-10

### Added

- Created the original LifeAgent / JobOps Guard scaffold for generic job portal monitoring, JD review, form inspection, and dashboard exploration.
- Added root `jobops` package, React/Vite frontend, synthetic Greenhouse/Lever/Workday fixtures, and broad job-application workflow tests.

### Superseded

- This version has been superseded by the SentinelDesk direction. The old implementation was intentionally removed to avoid splitting the project across two incompatible product narratives.
