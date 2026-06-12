# UI Contract: Calendar + AI Assistant

This is the stable handoff contract between the SentinelDesk backend and the calendar UI implemented from the design package `design_handoff_calendar_ai/` (selected direction **B′** — warm-paper Bento month grid + Discord-style assistant panel, spec in `directionBD.jsx` and its README).

The UI is a static page served by the stdlib dashboard server: `sentineldesk/static/calendar.html`, mounted at `/` (with `/calendar` as an alias). The legacy monitor ops dashboard lives at `/ops` and is linked from the assistant panel header. No build step, no external dependencies; Google Fonts are the only remote asset and the page must degrade gracefully without them.

Regression tests for every shape below live in `tests/test_ui_contract.py`. Sample responses (generated from `fixtures/ui/sample_emails.json`, fully synthetic) are committed next to this document:

- `fixtures/ui/calendar_events.sample.json`
- `fixtures/ui/tasks.sample.json`
- `fixtures/ui/daily_summary.sample.json`
- `fixtures/ui/ask_answer.sample.json`

Regenerate samples by re-running the ingest + endpoint functions over `sample_emails.json` (see `tests/test_ui_contract.py::UiFixtureSampleTests` which verifies the committed samples still match the live shapes).

## Endpoints

### GET `/api/calendar/events` → `CalendarItem[]`

Source of truth for every calendar surface (month/week/day/agenda). One item per local calendar draft, sorted by `date_key` then title.

| Field | Type | Notes |
| --- | --- | --- |
| `event_id` | string | stable id; use in sync/review calls |
| `title` | string | display title |
| `date_text` | string | raw extracted date text |
| `date_key` | string | ISO `YYYY-MM-DD`, or `""` when the date text cannot be parsed (e.g. relative deadlines) |
| `severity` | string | `low \| medium \| high \| critical` (free-form, treat unknown as `medium`) |
| `confidence` | number | 0..1 extraction confidence |
| `status` | string | draft lifecycle: `draft \| synced \| uncertain` |
| `sync_state` | string | `local_draft \| ics_exported \| google_synced \| apple_synced` |
| `approval_state` | string | `draft` (pending) \| `approved` (confirmed) |
| `uncertain` | boolean | true when confidence < 0.8 or status is uncertain |
| `source_ids` | string[] | evidence references (`email:<id>`, `run_<id>`, ...) |
| `source_trust` | string | `email_evidence \| portal_verified \| trusted_doc_context \| local_evidence` |
| `source_count` | number | length of `source_ids` |
| `evidence_uri` | string | primary evidence reference |
| `reminders` | array | reminder policy entries (opaque to the UI) |

### GET `/api/tasks?status=<optional>&kind=<optional>&limit=<optional>` → `Task[]`

Reviewable work items aggregated from calendar drafts and email facts (deadline facts already represented by a draft are deduplicated into the `calendar:` task). Email facts are grouped by message and kind, so a single bill with multiple amounts produces one review card with all values instead of several near-duplicate cards.

Optional filters are applied server-side before the list is returned: `status` must be one of `new`, `reviewed`, `ignored`, `needs_verification`, or `done`; `kind` must be one of `deadline`, `amount`, or `action`; `limit` defaults to 100. Invalid filters return HTTP 400 `{error}`. The CLI mirrors this shape with `sentineldesk tasks list --status ... --kind ... --limit ...`.

Common fields present on every task (calendar-derived tasks additionally carry `created_at`; email-derived tasks additionally carry `subject`, `sender`, `received_at`):

| Field | Type | Notes |
| --- | --- | --- |
| `task_id` | string | `calendar:<event_id>` or `email:<fingerprint>` |
| `kind` | string | `deadline \| amount \| action` |
| `title` | string | display title |
| `value` | string | extracted value (date text, dollar amount, action span) |
| `values` | string[] | all unique values represented by this review item; length is usually 1 |
| `fact_count` | number | number of unique extracted values represented by this item |
| `due_date` | string | date text for deadline tasks, else `""` |
| `severity` | string | same scale as calendar items |
| `confidence` | number | 0..1 |
| `source_type` | string | `calendar_draft` or the email source type |
| `source_refs` | string[] | evidence references |
| `primary_source` | string | first evidence reference |
| `evidence` | string | evidence URI or extracted context snippet |
| `calendar_event_id` | string | linked calendar draft id, `""` for email-only tasks |
| `sync_state` | string | linked draft sync state, `""` for email-only tasks |
| `updated_at` | string | last change timestamp |
| `needs_verification` | boolean | true when evidence is missing or confidence < 0.7 |
| `status` | string | review state: `new \| reviewed \| ignored \| needs_verification \| done` |
| `review_note` | string | last review note |
| `review_actor` / `reviewed_at` | string | last review actor/timestamp (empty when never reviewed) |

### POST `/api/tasks/review?task_id=&status=&note=` → review receipt

Sets the review state (audited, local-only). Response: `{task_id, status, note, actor, updated_at, task}` where `task` is the refreshed Task or `null`. Invalid status → HTTP 400 `{error}`.

The calendar assistant reads the full `/api/tasks` queue. Calendar-derived tasks drive pending calendar suggestion visibility; non-calendar email tasks (`amount` and `action`, plus any future email-only deadline tasks) render as review cards. Buttons map to `status=done`, `status=needs_verification`, `status=reviewed`, and `status=ignored`. These calls write only local `task.review` audit events and must not trigger email sends, portal writes, or external calendar writes.

### POST `/api/tasks/review/bulk` → bulk review receipt

Confirmation-gated local bulk review for the current filtered task queue. Preferred UI request body:

```json
{
  "task_ids": ["email:..."],
  "status": "done",
  "note": "bulk reviewed from calendar assistant: done",
  "confirm": true,
  "confirmation_id": "ui-task-bulk-<epoch>",
  "filter": {"kind": "amount", "status": "active"}
}
```

Without `confirm: true`, the response is blocked with `allowed: false`, `reason: "confirmation_required"`, and no task status changes. Confirmed requests require a single-use `confirmation_id`; replay returns `allowed: false`, `reason: "confirmation_id_already_consumed"`. Successful responses include `allowed`, `reason`, `status`, `confirmation_id`, `filters`, `requested_count`, `matched_count`, `reviewed_count`, `missing_task_ids`, `task_ids`, `tasks`, and `external_writes_performed: false`. The operation writes a local approval record, a `task.review.bulk` audit event, and one existing `task.review` audit event per changed task. It never sends email, refreshes Gmail, submits a portal form, or writes an external calendar.

The CLI mirrors this with `sentineldesk tasks bulk-review --kind ... --filter-status ... --status ... --confirm --confirmation-id ...`.

### GET `/api/tasks/evidence?task_id=` → task evidence drill-down

Read-only source drill-down for a review task. Returns `{task_id, task, sources, source_count, external_network, external_writes_performed}`. Each source includes local email metadata (`message_id`, `thread_id`, `sender`, `subject`, `received_at`), `body_preview`, attachment counts/names, and `matched_facts` with `kind`, `value`, `confidence`, and evidence snippets. This endpoint does not write an audit event, refresh Gmail, or call any external system.

### GET `/api/daily/summary?task_limit=&calendar_limit=` → daily landing snapshot

Read-only daily landing summary for the assistant panel. It returns stored email counts, fact counts, grouped task queue counts and optional queue rows, local calendar draft counts and optional calendar items, redacted connector readiness, safety flags, and safe next actions. This endpoint does **not** write a `daily.run` audit event; it is safe for page load and refresh polling.

Top-level fields: `status`, `generated_at`, `mode`, `sync`, `email`, `tasks`, `calendar`, `connectors`, `safety`, `next_actions`.

### POST `/api/daily/run?task_limit=&calendar_limit=` → daily landing run

Runs the same stored-evidence daily summary from the dashboard and writes a local `daily.run` audit event. This dashboard route does not refresh Gmail or perform external calendar writes; external reads still happen through the CLI `daily run --sync-gmail` path, and external calendar writes remain behind `/api/calendar/sync?confirm=1`.

### POST `/api/calendar/sync?confirm=1&confirmation_id=&event_id=&destination=ics` → sync receipt

Confirmation-gated local ICS export. Without `confirm=1` the call is blocked and audited (`allowed: false`). Confirmation IDs are single-use; reuse is rejected. Response fields the UI relies on: `allowed` (boolean), `event_ids` (string[]), `reason`. On success the affected drafts move to `sync_state: "ics_exported"`, `status: "synced"`, and `/api/calendar/events` reports `approval_state: "approved"`.

Only `destination=ics` is available from the dashboard; Google/Apple destinations are CLI-only and remain deferred.

### POST `/api/calendar/drafts/update?event_id=&date=&title=&severity=` → `{updated, external_write: false}`

Local draft edit. Resets the draft to `status: "draft"` / `sync_state: "local_draft"` (a previously synced draft must be re-confirmed) and writes a `calendar.edit` audit event.

### POST `/api/ask` (JSON body `{"question": "..."}`) → `AgentAnswer`

Exposes the assistant layer to the chat panel. Same shape as the CLI `ask` command:

| Field | Type | Notes |
| --- | --- | --- |
| `intent` | string | routed intent (`latest_deadline`, `alert_explanation`, `policy_question`, ...) |
| `answer` | string | assistant text |
| `confidence` | string | `high \| medium \| uncertain` |
| `uncertain` | boolean | fail-loud flag; render distinctly |
| `requires_confirmation` | boolean | true when the request would need a confirmed write |
| `tool_calls` | string[] | tools the workflow ran |
| `citations` | object[] | `{source_id, source_type, evidence, captured_at}` — render as evidence chips |
| `metadata` | object | includes `workflow_engine`, `workflow_trace`, `planned_tools` |

Missing/empty `question` → HTTP 400 `{error}`. The dashboard path loads locally stored email evidence (most recent 200 persisted messages, cited as `stored_email:<id>`), so latest-deadline/amount questions can reach verified answers once mail has been synced or scanned; conflicting stored deadlines still answer `uncertain` with the safer earlier candidate, and policy questions use the local RAG index.

When a local model provider is configured (`[model] provider = "ollama"` in `config.toml`), verified answers may be rephrased by the model before returning. The facts stay deterministic: uncertain answers and confirmation boundaries are never sent to the model, every date/amount in the deterministic answer must survive the rewrite (otherwise the deterministic text is returned unchanged), and `metadata` gains two optional keys the UI may surface but must not require:

- `metadata.model_call`: `{created_at, provider, model, stage, intent, status, prompt_tokens, completion_tokens, duration_ms, detail}` — `status: "ok"` means the rewrite was used; any `skipped_*`/`fallback_*` status means the deterministic text was returned.
- `metadata.deterministic_answer`: the original deterministic text when a rewrite was applied.

`GET /api/model/calls` returns `{summary, calls}` for the cost/latency attribution view: totals, per-status counts, per-model token/latency aggregates, and the most recent call rows (no question or answer text is persisted).

## Design Mapping Rules

How backend fields drive the B′ visual spec:

| Design concept | Backend rule |
| --- | --- |
| **Pending chip** (dashed outline) | `approval_state == "draft"` |
| **Confirmed chip** (solid soft bg) | `approval_state == "approved"` |
| Event type color | pending → `ai` purple (`#6A5BD0`); confirmed → `deadline` terracotta (`#B14228`). `meeting`/`personal` palettes are reserved for future sources and must not be synthesized from current data |
| Uncertain marker | `uncertain == true` → append `?` marker on the chip/row |
| Source caption (agenda rows, cards) | `source_trust` → `email_evidence`: "邮件证据", `portal_verified`: "门户已验证", `trusted_doc_context`: "可信文档", `local_evidence`: "本地证据" |
| Calendar placement | use `date_key`; items with empty `date_key` (relative deadlines) appear only in the Agenda view under a trailing "日期待定" group, never on month/week/day grids |
| All-day vs timed | current extraction has no time-of-day → all events render as all-day chips; the week/day time grid renders the layout (hours, gridlines, now line) with all-day strip populated |
| **确认加入日历** button | `POST /api/calendar/sync?confirm=1&confirmation_id=ui-<event_id>-<epoch>&event_id=<event_id>&destination=ics`; on `allowed: true` re-fetch events (chip turns solid) |
| **忽略** button | `POST /api/tasks/review?task_id=calendar:<event_id>&status=ignored`; UI hides the pending suggestion; the draft itself stays in local storage (retention controls own deletion) |
| Assistant daily embed | computed from `/api/daily/summary`: stored mail, grouped review queue, local calendar drafts, connector readiness, and external-write boundary |
| Assistant task review card | computed from `/api/tasks`: non-calendar amount/action tasks render with value chips, evidence snippet, confidence, a local-only `查看证据` drill-down from `/api/tasks/evidence`, and local-only `done`, `needs_verification`, `reviewed`, `ignored` controls |
| Assistant task queue controls | client-side filters over the loaded `/api/tasks` rows: kind (`all/deadline/amount/action`), status (`active/new/needs_verification/reviewed/done/ignored/all`), plus cursor navigation (`task-prev`, `task-next`, `show-task`) so large queues can be reviewed without cycling one unfiltered card at a time |
| Assistant bulk task controls | `task-bulk-done`, `task-bulk-reviewed`, `task-bulk-ignored`, and `task-bulk-needs-verification` use `window.confirm`, send the currently filtered `task_ids` to `/api/tasks/review/bulk`, and re-fetch local state after `allowed: true` |
| Assistant calendar embed | computed client-side from `/api/calendar/events` + `/api/tasks`: counts of pending/confirmed/uncertain in the visible range |
| Composer | sends to `/api/ask`; render `citations` as evidence chips and `uncertain` answers with the uncertainty style |
| Now line | client clock; render only in today's column within 07:00–21:00 |

## Privacy Boundary

The page is local-only, same-origin (`127.0.0.1`), and renders only local evidence. No external requests besides Google Fonts. Event titles and evidence strings may contain personal data — the calendar page is a private surface like the rest of the dashboard and must never be included in redacted share packages or screenshots for publication.
