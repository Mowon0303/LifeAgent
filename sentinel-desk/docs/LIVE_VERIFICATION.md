# Live Verification

LifeAgent keeps external credentials out of the database. Live checks use environment-variable secret references and only persist redacted readiness reports, connector cursors, scopes, and non-secret metadata.

## Connector Dependency Setup

Use a project-local virtual environment for live Gmail now, deferred Google/Apple Calendar checks later, and optional agent dependencies:

```bash
python3 -B -m venv .agent-venv
.agent-venv/bin/python -m pip install -e '.[integrations]'
```

To exercise both live connector dependencies and the optional LangGraph path in the same environment:

```bash
.agent-venv/bin/python -m pip install -e '.[agent,integrations]'
```

Print the redacted live setup template before adding credentials:

```bash
.agent-venv/bin/python -B -m sentineldesk integrations env-template --account user@example.com
```

This reports which env refs are available, which checks to run next, which OAuth command can create the Google token file, and which sync commands create live evidence. It never prints secret values.

For the Gmail-first real-account handoff, use the readiness commands below directly or use the preflight script with only Gmail sync enabled. By default the script prints the live setup template, writes redacted readiness packages, runs completion audit, scans redacted outputs with `privacy audit`, writes a clean source release ZIP, and audits the extracted release tree without Gmail sync or calendar writes:

```bash
.agent-venv/bin/python -B -m sentineldesk --home .demo integrations handoff --account user@example.com --output .demo/live-verification-handoff.md
bash scripts/live_verification_preflight.sh
SENTINEL_LIVE_DRY_RUN=1 bash scripts/live_verification_preflight.sh
```

The handoff checklist is Markdown for human execution. It lists completion gates, commands, side-effect labels such as `external_read` and `external_calendar_write`, approval requirements, and the final source release audit commands without printing secret values.

The script only performs sensitive steps when explicitly enabled:

```bash
SENTINEL_LIVE_RUN_GOOGLE_TOKEN=1 bash scripts/live_verification_preflight.sh
SENTINEL_LIVE_RUN_GMAIL_SYNC=1 bash scripts/live_verification_preflight.sh
SENTINEL_LIVE_SEED_CALENDAR_DRAFT=1 bash scripts/live_verification_preflight.sh
SENTINEL_LIVE_RUN_CALENDAR_WRITES=1 SENTINEL_LIVE_APPROVED=1 bash scripts/live_verification_preflight.sh
SENTINEL_LIVE_REQUIRE_READY=1 bash scripts/live_verification_preflight.sh
SENTINEL_LIVE_RUN_RELEASE_PACKAGE=0 bash scripts/live_verification_preflight.sh
```

Use Gmail as the first live source. Calendar live writes are a later action-layer milestone, not the current Gmail-first completion gate. If that milestone is resumed and the Gmail query does not produce a safe test draft, seed one local verification draft before calendar sync:

```bash
.agent-venv/bin/python -B -m sentineldesk --home .demo integrations seed-calendar-draft
```

This creates only a local draft and audit event. It does not write to external calendars. The current Gmail-first release gate is a real readonly Gmail sync, `integrations check --suite gmail --require-ready --package`, `privacy audit --require-clean`, and a clean source release-package plus release-audit. The later full Calendar gate is `SENTINEL_LIVE_RUN_GMAIL_SYNC=1 SENTINEL_LIVE_SEED_CALENDAR_DRAFT=1 SENTINEL_LIVE_RUN_CALENDAR_WRITES=1 SENTINEL_LIVE_APPROVED=1 SENTINEL_LIVE_REQUIRE_READY=1 bash scripts/live_verification_preflight.sh`, which also requires the final redacted-output privacy audit and clean source release-package plus release-audit to pass.

## Gmail OAuth Readiness

Required environment variables:

```bash
export SENTINEL_GOOGLE_CREDENTIALS_JSON='{"installed":...}'
export SENTINEL_GOOGLE_TOKEN_JSON='{"token":...}'
```

Generate the token JSON locally without printing the token to the terminal:

```bash
.agent-venv/bin/python -B -m sentineldesk --home .demo integrations google-token \
  --credentials-env SENTINEL_GOOGLE_CREDENTIALS_JSON \
  --token-env SENTINEL_GOOGLE_TOKEN_JSON
export SENTINEL_GOOGLE_TOKEN_JSON="$(cat .demo/secrets/google-token.json)"
```

The token command runs a local Google OAuth browser flow, writes `.demo/secrets/google-token.json` with owner-only `0600` permissions, and prints only redacted metadata plus the export hint. By default it requests both Gmail readonly and Google Calendar events scopes. If you override scopes with `--scope`, repeat it for every required scope:

```bash
.agent-venv/bin/python -B -m sentineldesk --home .demo integrations google-token \
  --scope gmail.readonly \
  --scope calendar.events
```

Run a readiness report:

```bash
.agent-venv/bin/python -B -m sentineldesk --home .demo integrations check --suite gmail --account user@example.com
```

Use `--require-ready` in CI or a release preflight. It exits non-zero unless every check in the selected suite is ready:

```bash
.agent-venv/bin/python -B -m sentineldesk --home .demo integrations check --suite gmail --require-ready --package
.agent-venv/bin/python -B -m sentineldesk --home .demo integrations check --suite all --require-ready
.agent-venv/bin/python -B -m sentineldesk --home .demo integrations check --suite all --require-ready --package
.agent-venv/bin/python -B -m sentineldesk --home .demo privacy release-package --source . --output /tmp/sentineldesk.release.zip
python3 -B -m zipfile -e /tmp/sentineldesk.release.zip /tmp/extracted-sentineldesk
.agent-venv/bin/python -B -m sentineldesk --home .demo privacy release-audit --path /tmp/extracted-sentineldesk --require-clean
.agent-venv/bin/python -B -m sentineldesk --home .demo integrations completion-audit --source-release-path /tmp/extracted-sentineldesk --require-ready
.agent-venv/bin/python -B -m sentineldesk --home .demo integrations handoff --account user@example.com --output .demo/live-verification-handoff.md
.agent-venv/bin/python -B -m sentineldesk --home .demo privacy audit --require-clean
```

After connector dependencies are installed but before real env secrets are configured, `--suite all --require-ready` should still fail with a `partial` report. The expected remaining missing checks are the user-approved Gmail/Calendar secret refs, token scope evidence, and the Gmail cursor created by a real sync.

Readiness reports distinguish secret availability from usable credential shape:

- `*.credentials` and `*.token` show whether the env ref exists.
- `*.credentials_format` checks that Google client credentials are JSON or base64 JSON and contain an `installed` or `web` OAuth client.
- `*.token_format` checks that the Google authorized-user token JSON has the API-client fields needed later.
- `*.token_scope` checks that the token includes Gmail readonly or Google Calendar events scopes.
- `apple_calendar.username_format` checks that the Apple Calendar username looks like an Apple ID email address.
- `apple_calendar.app_password_format` checks only the local shape of an Apple app-specific password, either four 4-character groups or a compact 16-character value.

Malformed secret values are reported as `invalid` with redacted refs only.

Run Gmail sync after user approval:

```bash
.agent-venv/bin/python -B -m sentineldesk --home .demo email sync-gmail --account user@example.com --query "deadline OR due"
```

The sync stores `connector_states.cursor`, OAuth scopes, and safe metadata. It does not store token JSON.

## Calendar Readiness

Calendar readiness is deferred until external calendar sync becomes a useful workflow. The local dashboard calendar, local drafts, local edits, and ICS preview remain available without this live-write milestone.

Google Calendar uses the same Google env refs plus the `calendar.events` scope. Apple Calendar uses app-password based CalDAV credentials:

```bash
export SENTINEL_APPLE_ID='user@example.com'
export SENTINEL_APPLE_APP_PASSWORD='abcd-efgh-ijkl-mnop'
.agent-venv/bin/python -B -m sentineldesk --home .demo integrations check --suite calendar
```

Calendar writes remain confirmation-gated. The dashboard can export local ICS files; the CLI can preview and then sync local calendar drafts to Google or Apple Calendar:

```bash
.agent-venv/bin/python -B -m sentineldesk --home .demo calendar sync --destination google
.agent-venv/bin/python -B -m sentineldesk --home .demo calendar sync \
  --destination google \
  --confirm \
  --confirmation-id live-google-sandbox-001 \
  --calendar-id primary
.agent-venv/bin/python -B -m sentineldesk --home .demo calendar sync --destination apple
.agent-venv/bin/python -B -m sentineldesk --home .demo calendar sync \
  --destination apple \
  --confirm \
  --confirmation-id live-apple-sandbox-001
```

The unconfirmed commands write only blocked audit events. Google/Apple confirmed writes require a stable confirmation ID, create approval records, update local draft sync state, and use remote dedupe/update-before-create behavior when the client supports listing existing events.

`integrations check --suite calendar --require-ready` requires more than installed modules and available env refs. It also looks for non-sandbox confirmed `calendar.sync` approval records for Google and Apple Calendar. Run the confirmed sandbox-account writes first, then re-run the calendar readiness report so the redacted report proves actual external-write evidence.

## LangGraph Readiness

Use the same project-local virtual environment for the optional agent dependencies:

```bash
.agent-venv/bin/python -m pip install -e '.[agent]'
```

```bash
.agent-venv/bin/python -B -m sentineldesk --home .demo integrations check --suite langgraph --require-ready
```

If `langgraph` is installed, this builds the workflow path and reports `ready`. If not installed, the report is `missing` or `partial`, and `sentineldesk ask` continues to use the rule-graph fallback unless `--require-ready` is used.

The verified installed path reports `langgraph.graph` as available and builds the route/tools/finalize workflow as a `CompiledStateGraph`.

## Sandbox Connector Verification

Sandbox verification exercises the real local connector, calendar adapter, confirmation, approval, audit, and report code paths with fake clients. It does not require external credentials and does not prove a real Google or Apple account is ready.

```bash
python3 -m sentineldesk --home .demo integrations check --suite sandbox --account sandbox@example.com --require-ready
```

The sandbox report verifies:

- Gmail connector cursor persistence through the authenticated-client boundary.
- Email ingest, deadline extraction, and calendar draft generation.
- Google Calendar and Apple Calendar blocked-write behavior before confirmation.
- Confirmed calendar writes, durable approval records, and audit logs.

## Evidence Reports

Reports are written under:

```text
<SENTINEL_HOME>/artifacts/integrations/
```

They are also listed by:

```bash
python3 -m sentineldesk --home .demo integrations reports
python3 -m sentineldesk --home .demo integrations package latest
```

The report format is intentionally safe for sharing internally: secret values are represented as `env:NAME:***`; readiness and cursor metadata are visible. Use `integrations check --package` for the final live readiness run, or `integrations package latest` after an already-persisted report, to create a redacted ZIP with `README.md`, `manifest.json`, `verification.redacted.json`, and `report.html`.

Use `integrations completion-audit --source-release-path /tmp/extracted-sentineldesk --require-ready` after the final readiness package and source release audit run. It is stricter than a transient readiness check: current all-suite readiness must be ready, the latest persisted all-suite report must have a redacted package on disk, the redacted-output privacy requirement must be clean, and the extracted source release tree must pass `privacy release-audit --require-clean`. Then run `privacy audit --require-clean` as an explicit standalone scan over the same redacted package/report set before sharing.

The completion audit also returns `readiness_action_plan`. Each action includes:

- `missing_checks`: the exact checks blocking that step.
- `commands`: redacted commands to run next.
- `side_effect`: `local_only`, `external_read`, or `external_calendar_write`.
- `requires_user_approval`: whether the user must explicitly approve the step.

Use that action plan, or the rendered `integrations handoff` Markdown, as the checklist for the remaining real-account work. It intentionally keeps Gmail sync and calendar writes separate so a read-only mailbox check cannot silently become an external calendar write.
