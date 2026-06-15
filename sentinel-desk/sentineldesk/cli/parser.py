"""Argument parser wiring + the ``main`` entry point.

Each subcommand binds ``func=cmd_*`` from a command module; ``main`` parses the
argv and dispatches. This file holds only the argparse tree — no command logic.
"""

from __future__ import annotations

import argparse

from .. import __version__
from .commands_calendar import cmd_calendar_edit, cmd_calendar_sync
from .commands_core import (
    cmd_acceptance_first_run,
    cmd_chrome_launch,
    cmd_doctor,
    cmd_init,
    cmd_plan_status,
    cmd_serve,
)
from .commands_demo import (
    cmd_demo_apply,
    cmd_demo_record_prep,
    cmd_demo_scenarios,
    cmd_demo_seed,
)
from .commands_email import (
    cmd_ask,
    cmd_daily_run,
    cmd_email_reprocess,
    cmd_email_scan,
    cmd_email_sync_gmail,
)
from .commands_inspect import (
    cmd_approvals_list,
    cmd_audit_list,
    cmd_connectors_state,
    cmd_eval_agent_routing,
    cmd_eval_calendar_slots,
    cmd_eval_email_extract,
    cmd_model_calls,
    cmd_model_status,
)
from .commands_integrations import (
    cmd_integrations_check,
    cmd_integrations_completion_audit,
    cmd_integrations_env_template,
    cmd_integrations_gmail_readiness,
    cmd_integrations_gmail_sync_diagnostics,
    cmd_integrations_google_token,
    cmd_integrations_handoff,
    cmd_integrations_package,
    cmd_integrations_reports,
    cmd_integrations_seed_calendar_draft,
)
from .commands_monitor import (
    cmd_alerts,
    cmd_evidence,
    cmd_runs,
    cmd_targets,
    cmd_watch_add,
    cmd_watch_run,
)
from .commands_privacy import (
    cmd_privacy_audit,
    cmd_privacy_release_audit,
    cmd_privacy_release_package,
    cmd_retention_purge,
)
from .commands_rag import (
    cmd_rag_docs,
    cmd_rag_embed_emails,
    cmd_rag_index,
    cmd_rag_search,
)
from .commands_tasks import (
    cmd_tasks_bulk_review,
    cmd_tasks_history,
    cmd_tasks_list,
    cmd_tasks_receipt,
    cmd_tasks_review,
    cmd_tasks_undo,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentineldesk", description="Fail-loud local portal sentinel.")
    parser.add_argument("--home", help="Override SentinelDesk home directory")
    parser.add_argument("--version", action="version", version=f"SentinelDesk {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser("init", help="Initialize local config, database, and demo fixtures")
    init_parser.set_defaults(func=cmd_init)

    doctor_parser = sub.add_parser("doctor", help="Check local readiness")
    doctor_parser.set_defaults(func=cmd_doctor)

    acceptance = sub.add_parser("acceptance", help="Run product acceptance checks")
    acceptance_sub = acceptance.add_subparsers(dest="acceptance_command", required=True)
    acceptance_first = acceptance_sub.add_parser("first-run", help="Prepare and verify the local first-run MVP")
    acceptance_first.add_argument("--email-json", help="Synthetic email fixture to use. Defaults to fixtures/ui/sample_emails.json")
    acceptance_first.add_argument("--port", type=int, default=8787, help="Dashboard port to include in the printed serve command")
    acceptance_first.set_defaults(func=cmd_acceptance_first_run)

    demo = sub.add_parser("demo", help="Demo fixture helpers")
    demo_sub = demo.add_subparsers(dest="demo_command", required=True)
    demo_seed = demo_sub.add_parser("seed", help="Seed synthetic high-stakes portal targets")
    demo_seed.set_defaults(func=cmd_demo_seed)
    demo_scenarios = demo_sub.add_parser("scenarios", help="List synthetic portal scenarios")
    demo_scenarios.add_argument("--kind", choices=["generic", "opt", "appointment", "lease"])
    demo_scenarios.set_defaults(func=cmd_demo_scenarios)
    demo_apply = demo_sub.add_parser("apply", help="Apply a synthetic scenario to a demo target")
    demo_apply.add_argument("scenario")
    demo_apply.add_argument("--target-name", help="Override the scenario target name")
    demo_apply.add_argument("--run", action="store_true", help="Run the target after applying the scenario")
    demo_apply.set_defaults(func=cmd_demo_apply)
    demo_record = demo_sub.add_parser("record-prep", help="Prepare a complete local state for manual portfolio demo recording")
    demo_record.add_argument("--port", type=int, default=8787, help="Dashboard port to include in the printed serve command")
    demo_record.set_defaults(func=cmd_demo_record_prep)

    targets = sub.add_parser("targets", help="List watch targets")
    targets.set_defaults(func=cmd_targets)

    watch = sub.add_parser("watch", help="Manage and run watches")
    watch_sub = watch.add_subparsers(dest="watch_command", required=True)
    watch_add = watch_sub.add_parser("add", help="Add or update a watch target")
    watch_add.add_argument("--name", required=True)
    watch_add.add_argument("--url", required=True)
    watch_add.add_argument("--kind", default="generic", choices=["generic", "opt", "appointment", "job", "lease"])
    watch_add.add_argument("--low-stakes", action="store_true", help="Do not fail loud on unknown status")
    watch_add.set_defaults(func=cmd_watch_add)
    watch_run = watch_sub.add_parser("run", help="Run one or all watches")
    watch_run.add_argument("--name", help="Run only one target by name")
    watch_run.set_defaults(func=cmd_watch_run)

    alerts = sub.add_parser("alerts", help="List non-empty alerts")
    alerts.add_argument("--limit", type=int, default=50)
    alerts.set_defaults(func=cmd_alerts)

    runs = sub.add_parser("runs", help="List recent runs")
    runs.add_argument("--limit", type=int, default=50)
    runs.set_defaults(func=cmd_runs)

    evidence = sub.add_parser("evidence", help="Print an evidence bundle by run id")
    evidence.add_argument("run_id")
    evidence.add_argument("--redacted", action="store_true", help="Print the privacy-safe evidence bundle")
    evidence.add_argument("--report", action="store_true", help="Print the generated redacted HTML report path")
    evidence.add_argument("--package", action="store_true", help="Create a redacted shareable evidence ZIP package and print its path")
    evidence.set_defaults(func=cmd_evidence)

    plan = sub.add_parser("plan", help="Show plan-tracker status")
    plan_sub = plan.add_subparsers(dest="plan_command", required=True)
    plan_status = plan_sub.add_parser("status", help="Show completed plans and the next plan to complete")
    plan_status.add_argument("--json", action="store_true", help="Print machine-readable plan status")
    plan_status.set_defaults(func=cmd_plan_status)

    ask = sub.add_parser("ask", help="Ask the assistant layer with tool-first routing")
    ask.add_argument("question")
    ask.add_argument("--email-json", help="Local JSON file containing email messages for offline verification")
    ask.set_defaults(func=cmd_ask)

    daily = sub.add_parser("daily", help="Run the Gmail-first daily landing workflow")
    daily_sub = daily.add_subparsers(dest="daily_command", required=True)
    daily_run = daily_sub.add_parser("run", help="Refresh optional email evidence and summarize tasks/calendar drafts")
    daily_run.add_argument("--email-json", help="Optional local JSON email export to ingest before building the daily queue")
    daily_run.add_argument("--sync-gmail", action="store_true", help="Explicitly refresh Gmail through readonly OAuth before summarizing")
    daily_run.add_argument("--query", help="Optional email/Gmail search query for this refresh")
    daily_run.add_argument("--since", help="Override incremental Gmail cursor/date. Defaults to stored connector cursor.")
    daily_run.add_argument("--limit", type=int, default=50)
    daily_run.add_argument("--task-limit", type=int, default=12)
    daily_run.add_argument("--calendar-limit", type=int, default=20)
    daily_run.add_argument(
        "--reprocess-stored",
        action="store_true",
        help="Re-run current extractors over already stored local email before summarizing",
    )
    daily_run.add_argument("--reprocess-limit", type=int, default=500)
    daily_run.add_argument(
        "--no-calendar-drafts",
        action="store_true",
        help="When reprocessing, update email facts without upserting local calendar drafts",
    )
    daily_run.add_argument(
        "--embed",
        action="store_true",
        help="Incrementally embed newly synced mail into the RAG store (also enabled by [model] auto_embed)",
    )
    daily_run.add_argument("--account", default="default")
    daily_run.add_argument("--actor", default="user")
    daily_run.add_argument("--credentials-env", default="SENTINEL_GOOGLE_CREDENTIALS_JSON")
    daily_run.add_argument("--token-env", default="SENTINEL_GOOGLE_TOKEN_JSON")
    daily_run.set_defaults(func=cmd_daily_run)

    rag = sub.add_parser("rag", help="Build and search the local RAG index")
    rag_sub = rag.add_subparsers(dest="rag_command", required=True)
    rag_index = rag_sub.add_parser("index", help="Index one local document into the persistent RAG store")
    rag_index.add_argument("file")
    rag_index.add_argument("--source-id")
    rag_index.add_argument("--source-type", default="local_doc")
    rag_index.add_argument("--trust-label", default="user_imported")
    rag_index.add_argument("--title", default="")
    rag_index.add_argument("--metadata", action="append", default=[], help="Attach document metadata as key=value; repeat for multiple values")
    rag_index.set_defaults(func=cmd_rag_index)
    rag_search = rag_sub.add_parser("search", help="Search the persistent RAG store")
    rag_search.add_argument("query")
    rag_search.add_argument("--limit", type=int, default=5)
    rag_search.add_argument("--mode", choices=["keyword", "semantic", "hybrid"], default="keyword",
                            help="keyword (default), semantic (embeddings), or hybrid (both, rank-fused)")
    rag_search.set_defaults(func=cmd_rag_search)
    rag_embed = rag_sub.add_parser("embed-emails", help="Chunk + embed stored emails into the RAG store (new-only by default)")
    rag_embed.add_argument("--limit", type=int, default=500)
    rag_embed.add_argument("--all", action="store_true", help="Re-embed every email, not just newly arrived ones")
    rag_embed.set_defaults(func=cmd_rag_embed_emails)
    rag_docs = rag_sub.add_parser("docs", help="List indexed RAG documents")
    rag_docs.add_argument("--limit", type=int, default=50)
    rag_docs.set_defaults(func=cmd_rag_docs)

    model = sub.add_parser("model", help="Inspect configured model provider")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    model_status = model_sub.add_parser("status", help="Show active model provider and optional dependency availability")
    model_status.set_defaults(func=cmd_model_status)
    model_calls = model_sub.add_parser("calls", help="Show model call cost/latency attribution (tokens, duration, outcomes)")
    model_calls.add_argument("--limit", type=int, default=50)
    model_calls.set_defaults(func=cmd_model_calls)

    evals = sub.add_parser("eval", help="Run golden-set evals against extraction layers")
    evals_sub = evals.add_subparsers(dest="eval_command", required=True)
    eval_email = evals_sub.add_parser("email-extract", help="Score email fact extraction against the golden set")
    eval_email.add_argument("--golden", default="evals/golden", help="Golden JSONL file or directory")
    eval_email.add_argument("--report-md", help="Write a Markdown eval report to this path")
    eval_email.add_argument("--json", action="store_true", help="Print the full JSON report")
    eval_email.set_defaults(func=cmd_eval_email_extract)

    def _add_eval_model_args(parser: Any) -> None:
        parser.add_argument("--provider", default="local", help="local (keyword-only) or ollama")
        parser.add_argument("--model", default="qwen2.5:7b", help="Model id when --provider ollama")
        parser.add_argument("--base-url", default="http://127.0.0.1:11434", help="Ollama base URL")
        parser.add_argument("--json", action="store_true", help="Print the full JSON report")

    eval_routing = evals_sub.add_parser("agent-routing", help="Score intent routing (keyword + optional model)")
    eval_routing.add_argument("--golden", default="evals/golden/agent/agent_routing.jsonl", help="Golden JSONL file")
    _add_eval_model_args(eval_routing)
    eval_routing.set_defaults(func=cmd_eval_agent_routing)

    eval_slots = evals_sub.add_parser("calendar-slots", help="Score calendar-event slot extraction (needs a model)")
    eval_slots.add_argument("--golden", default="evals/golden/agent/calendar_slots.jsonl", help="Golden JSONL file")
    _add_eval_model_args(eval_slots)
    eval_slots.set_defaults(func=cmd_eval_calendar_slots)

    email = sub.add_parser("email", help="Ingest and inspect local email evidence")
    email_sub = email.add_subparsers(dest="email_command", required=True)
    email_scan = email_sub.add_parser("scan", help="Scan local JSON email export and draft calendar events")
    email_scan.add_argument("--json", required=True, help="Local JSON file containing email messages")
    email_scan.add_argument("--query", help="Optional query to filter messages before ingest")
    email_scan.add_argument("--limit", type=int, default=50)
    email_scan.set_defaults(func=cmd_email_scan)
    email_sync_gmail = email_sub.add_parser("sync-gmail", help="Sync Gmail through an authenticated Google client")
    email_sync_gmail.add_argument("--query", help="Optional Gmail search query")
    email_sync_gmail.add_argument("--since", help="Override incremental cursor/date. Defaults to stored connector cursor.")
    email_sync_gmail.add_argument("--limit", type=int, default=50)
    email_sync_gmail.add_argument("--account", default="default")
    email_sync_gmail.add_argument("--credentials-env", default="SENTINEL_GOOGLE_CREDENTIALS_JSON")
    email_sync_gmail.add_argument("--token-env", default="SENTINEL_GOOGLE_TOKEN_JSON")
    email_sync_gmail.set_defaults(func=cmd_email_sync_gmail)
    email_reprocess = email_sub.add_parser("reprocess", help="Re-run current extractors over stored local email evidence")
    email_reprocess.add_argument("--limit", type=int, default=500)
    email_reprocess.add_argument("--no-calendar-drafts", action="store_true", help="Update stored facts without upserting local calendar drafts")
    email_reprocess.set_defaults(func=cmd_email_reprocess)

    tasks = sub.add_parser("tasks", help="Review extracted LifeAgent tasks")
    tasks_sub = tasks.add_subparsers(dest="tasks_command", required=True)
    tasks_list = tasks_sub.add_parser("list", help="List task-review items derived from email facts and local drafts")
    tasks_list.add_argument("--status", choices=["new", "reviewed", "ignored", "needs_verification", "done"])
    tasks_list.add_argument("--kind", choices=["deadline", "amount", "action"])
    tasks_list.add_argument("--sort", choices=["priority", "due_date", "recent"])
    tasks_list.add_argument(
        "--view",
        default="all",
        choices=["all", "needs_verification", "payments", "deadlines_soon", "recently_changed"],
    )
    tasks_list.add_argument("--limit", type=int, default=100)
    tasks_list.set_defaults(func=cmd_tasks_list)
    tasks_review = tasks_sub.add_parser("review", help="Set review status for one task")
    tasks_review.add_argument("--task-id", required=True)
    tasks_review.add_argument("--status", required=True, choices=["new", "reviewed", "ignored", "needs_verification", "done"])
    tasks_review.add_argument("--note", default="")
    tasks_review.add_argument("--actor", default="user")
    tasks_review.set_defaults(func=cmd_tasks_review)
    tasks_history = tasks_sub.add_parser("history", help="List recent local task review actions and undo availability")
    tasks_history.add_argument("--limit", type=int, default=20)
    tasks_history.set_defaults(func=cmd_tasks_history)
    tasks_receipt = tasks_sub.add_parser("receipt", help="Summarize recent local task review changes")
    tasks_receipt.add_argument("--limit", type=int, default=50)
    tasks_receipt.add_argument("--recent-limit", type=int, default=5)
    tasks_receipt.set_defaults(func=cmd_tasks_receipt)
    tasks_bulk = tasks_sub.add_parser("bulk-review", help="Set review status for a filtered task queue after confirmation")
    tasks_bulk.add_argument("--status", required=True, choices=["new", "reviewed", "ignored", "needs_verification", "done"])
    tasks_bulk.add_argument("--kind", default="all", choices=["all", "deadline", "amount", "action"])
    tasks_bulk.add_argument(
        "--filter-status",
        default="active",
        choices=["active", "new", "reviewed", "ignored", "needs_verification", "done", "all"],
    )
    tasks_bulk.add_argument("--limit", type=int, default=100)
    tasks_bulk.add_argument("--note", default="")
    tasks_bulk.add_argument("--actor", default="user")
    tasks_bulk.add_argument("--confirm", action="store_true", help="Allow the local bulk review write")
    tasks_bulk.add_argument("--confirmation-id", default="", help="Required when --confirm is used")
    tasks_bulk.set_defaults(func=cmd_tasks_bulk_review)
    tasks_undo = tasks_sub.add_parser("undo", help="Undo a recent local task review audit event after confirmation")
    tasks_undo.add_argument("--audit-id", required=True, type=int)
    tasks_undo.add_argument("--actor", default="user")
    tasks_undo.add_argument("--confirm", action="store_true", help="Allow the local undo write")
    tasks_undo.add_argument("--confirmation-id", default="", help="Required when --confirm is used")
    tasks_undo.set_defaults(func=cmd_tasks_undo)

    calendar = sub.add_parser("calendar", help="Preview or sync drafted calendar deadline events")
    calendar_sub = calendar.add_subparsers(dest="calendar_command", required=True)
    calendar_sync = calendar_sub.add_parser("sync", help="Sync calendar drafts after explicit confirmation")
    calendar_sync.add_argument("--destination", choices=["ics", "google", "apple"], default="ics")
    calendar_sync.add_argument("--event-id", help="Sync only one local LifeAgent event id")
    calendar_sync.add_argument("--limit", type=int, default=200)
    calendar_sync.add_argument("--account", default="default")
    calendar_sync.add_argument("--calendar-id", default="", help="Google calendar id or Apple calendar URL/name; defaults to primary for Google and default for Apple")
    calendar_sync.add_argument("--actor", default="user")
    calendar_sync.add_argument("--confirm", action="store_true", help="Allow the calendar write")
    calendar_sync.add_argument("--confirmation-id", default="", help="Required stable confirmation id for external writes")
    calendar_sync.add_argument("--output", help="ICS output path when destination=ics")
    calendar_sync.add_argument("--google-credentials-env", default="SENTINEL_GOOGLE_CREDENTIALS_JSON")
    calendar_sync.add_argument("--google-token-env", default="SENTINEL_GOOGLE_TOKEN_JSON")
    calendar_sync.add_argument("--apple-user-env", default="SENTINEL_APPLE_ID")
    calendar_sync.add_argument("--apple-password-env", default="SENTINEL_APPLE_APP_PASSWORD")
    calendar_sync.set_defaults(func=cmd_calendar_sync)
    calendar_edit = calendar_sub.add_parser("edit", help="Edit a local calendar draft before external sync")
    calendar_edit.add_argument("--event-id", required=True)
    calendar_edit.add_argument("--title")
    calendar_edit.add_argument("--date", help="Replacement date text for the local deadline draft")
    calendar_edit.add_argument("--severity", choices=["low", "medium", "critical"])
    calendar_edit.add_argument("--actor", default="user")
    calendar_edit.set_defaults(func=cmd_calendar_edit)

    connectors = sub.add_parser("connectors", help="Inspect connector sync state")
    connectors_sub = connectors.add_subparsers(dest="connectors_command", required=True)
    connectors_state = connectors_sub.add_parser("state", help="List connector cursors and metadata")
    connectors_state.add_argument("--limit", type=int, default=50)
    connectors_state.set_defaults(func=cmd_connectors_state)

    integrations = sub.add_parser("integrations", help="Run live/sandbox integration readiness checks")
    integrations_sub = integrations.add_subparsers(dest="integrations_command", required=True)
    integrations_check = integrations_sub.add_parser("check", help="Check external integration readiness without exposing secrets")
    integrations_check.add_argument("--suite", choices=["all", "gmail", "calendar", "langgraph", "sandbox"], default="all")
    integrations_check.add_argument("--account", default="default")
    integrations_check.add_argument("--google-credentials-env", default="SENTINEL_GOOGLE_CREDENTIALS_JSON")
    integrations_check.add_argument("--google-token-env", default="SENTINEL_GOOGLE_TOKEN_JSON")
    integrations_check.add_argument("--apple-user-env", default="SENTINEL_APPLE_ID")
    integrations_check.add_argument("--apple-password-env", default="SENTINEL_APPLE_APP_PASSWORD")
    integrations_check.add_argument("--no-persist", action="store_true", help="Print the report without saving it")
    integrations_check.add_argument("--package", action="store_true", help="Also write a redacted ZIP package for this report")
    integrations_check.add_argument("--require-ready", action="store_true", help="Exit non-zero unless every check is ready")
    integrations_check.set_defaults(func=cmd_integrations_check)
    integrations_reports = integrations_sub.add_parser("reports", help="List stored integration verification reports")
    integrations_reports.add_argument("--limit", type=int, default=20)
    integrations_reports.set_defaults(func=cmd_integrations_reports)
    integrations_gmail_readiness = integrations_sub.add_parser(
        "gmail-readiness",
        help="Show the local-only first-run Gmail readiness checklist",
    )
    integrations_gmail_readiness.add_argument("--account", default="default")
    integrations_gmail_readiness.add_argument("--google-credentials-env", default="SENTINEL_GOOGLE_CREDENTIALS_JSON")
    integrations_gmail_readiness.add_argument("--google-token-env", default="SENTINEL_GOOGLE_TOKEN_JSON")
    integrations_gmail_readiness.set_defaults(func=cmd_integrations_gmail_readiness)
    integrations_gmail_diagnostics = integrations_sub.add_parser(
        "gmail-sync-diagnostics",
        help="Show local-only Gmail sync failure diagnostics and recovery guidance",
    )
    integrations_gmail_diagnostics.add_argument("--account", default="default")
    integrations_gmail_diagnostics.add_argument("--limit", type=int, default=20)
    integrations_gmail_diagnostics.set_defaults(func=cmd_integrations_gmail_sync_diagnostics)
    integrations_audit = integrations_sub.add_parser("completion-audit", help="Audit whether final live verification evidence is complete")
    integrations_audit.add_argument("--account", default="default")
    integrations_audit.add_argument("--google-credentials-env", default="SENTINEL_GOOGLE_CREDENTIALS_JSON")
    integrations_audit.add_argument("--google-token-env", default="SENTINEL_GOOGLE_TOKEN_JSON")
    integrations_audit.add_argument("--apple-user-env", default="SENTINEL_APPLE_ID")
    integrations_audit.add_argument("--apple-password-env", default="SENTINEL_APPLE_APP_PASSWORD")
    integrations_audit.add_argument("--source-release-path", default="/tmp/extracted-sentineldesk")
    integrations_audit.add_argument("--require-ready", action="store_true", help="Exit non-zero unless final live verification evidence is complete")
    integrations_audit.set_defaults(func=cmd_integrations_completion_audit)
    integrations_handoff = integrations_sub.add_parser("handoff", help="Render a human-readable live verification handoff checklist")
    integrations_handoff.add_argument("--account", default="default")
    integrations_handoff.add_argument("--google-credentials-env", default="SENTINEL_GOOGLE_CREDENTIALS_JSON")
    integrations_handoff.add_argument("--google-token-env", default="SENTINEL_GOOGLE_TOKEN_JSON")
    integrations_handoff.add_argument("--apple-user-env", default="SENTINEL_APPLE_ID")
    integrations_handoff.add_argument("--apple-password-env", default="SENTINEL_APPLE_APP_PASSWORD")
    integrations_handoff.add_argument("--source-release-path", default="/tmp/extracted-sentineldesk")
    integrations_handoff.add_argument("--output", help="Write the Markdown checklist to this path instead of stdout")
    integrations_handoff.add_argument("--require-ready", action="store_true", help="Exit non-zero unless final live verification evidence is complete")
    integrations_handoff.set_defaults(func=cmd_integrations_handoff)
    integrations_package = integrations_sub.add_parser("package", help="Create a redacted ZIP package for an integration verification report")
    integrations_package.add_argument("verification_id", help="Verification id to package, or 'latest'")
    integrations_package.add_argument("--output", help="Output ZIP path")
    integrations_package.set_defaults(func=cmd_integrations_package)
    integrations_seed_calendar = integrations_sub.add_parser(
        "seed-calendar-draft",
        help="Create a local verification calendar draft for live calendar sync tests",
    )
    integrations_seed_calendar.add_argument("--title", default="Deadline: LifeAgent live calendar verification")
    integrations_seed_calendar.add_argument("--date", default="2026-07-15")
    integrations_seed_calendar.add_argument("--source-id", default="live-verification:manual-calendar-draft")
    integrations_seed_calendar.add_argument("--evidence-uri", default="live-verification://manual-calendar-draft")
    integrations_seed_calendar.add_argument("--severity", choices=["low", "medium", "critical"], default="medium")
    integrations_seed_calendar.add_argument("--confidence", type=float, default=1.0)
    integrations_seed_calendar.add_argument("--actor", default="user")
    integrations_seed_calendar.set_defaults(func=cmd_integrations_seed_calendar_draft)
    integrations_env = integrations_sub.add_parser("env-template", help="Print redacted live-integration env setup commands")
    integrations_env.add_argument("--account", default="user@example.com")
    integrations_env.add_argument("--google-credentials-env", default="SENTINEL_GOOGLE_CREDENTIALS_JSON")
    integrations_env.add_argument("--google-token-env", default="SENTINEL_GOOGLE_TOKEN_JSON")
    integrations_env.add_argument("--apple-user-env", default="SENTINEL_APPLE_ID")
    integrations_env.add_argument("--apple-password-env", default="SENTINEL_APPLE_APP_PASSWORD")
    integrations_env.set_defaults(func=cmd_integrations_env_template)
    integrations_token = integrations_sub.add_parser("google-token", help="Run local Google OAuth and write token JSON without printing it")
    integrations_token.add_argument("--credentials-env", default="SENTINEL_GOOGLE_CREDENTIALS_JSON")
    integrations_token.add_argument("--token-env", default="SENTINEL_GOOGLE_TOKEN_JSON")
    integrations_token.add_argument("--token-output", help="Local token JSON output path. Defaults to <home>/secrets/google-token.json")
    integrations_token.add_argument("--scope", action="append", choices=["gmail.readonly", "calendar.events"], help="Google OAuth scope alias; repeat to limit scopes")
    integrations_token.add_argument("--port", type=int, default=0, help="Local OAuth callback port; 0 lets the OS choose")
    integrations_token.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically")
    integrations_token.set_defaults(func=cmd_integrations_google_token)

    audit = sub.add_parser("audit", help="Inspect local audit trail")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)
    audit_list = audit_sub.add_parser("list", help="List recent audit events")
    audit_list.add_argument("--limit", type=int, default=50)
    audit_list.set_defaults(func=cmd_audit_list)

    approvals = sub.add_parser("approvals", help="Inspect durable user approval records")
    approvals_sub = approvals.add_subparsers(dest="approvals_command", required=True)
    approvals_list = approvals_sub.add_parser("list", help="List recent approval records")
    approvals_list.add_argument("--limit", type=int, default=50)
    approvals_list.set_defaults(func=cmd_approvals_list)

    retention = sub.add_parser("retention", help="Preview or execute local retention purges")
    retention_sub = retention.add_subparsers(dest="retention_command", required=True)
    retention_purge = retention_sub.add_parser("purge", help="Purge local records older than --before")
    retention_purge.add_argument("--before", required=True, help="Delete records with timestamps before this ISO-like value")
    retention_purge.add_argument(
        "--source",
        action="append",
        choices=["email", "calendar", "tasks", "audit", "approvals"],
        default=[],
        help="Source to purge; repeat for multiple. Defaults to all sources.",
    )
    retention_purge.add_argument("--confirm", action="store_true", help="Actually delete matching local records")
    retention_purge.set_defaults(func=cmd_retention_purge)

    privacy = sub.add_parser("privacy", help="Audit redacted share outputs for private data leaks")
    privacy_sub = privacy.add_subparsers(dest="privacy_command", required=True)
    privacy_audit = privacy_sub.add_parser("audit", help="Scan redacted reports and share packages for unredacted private data")
    privacy_audit.add_argument("--path", help="Directory to scan. Defaults to <home>/artifacts")
    privacy_audit.add_argument("--require-clean", action="store_true", help="Exit non-zero when leaks are found")
    privacy_audit.set_defaults(func=cmd_privacy_audit)
    privacy_release = privacy_sub.add_parser("release-audit", help="Scan the project tree for local runtime artifacts before public release")
    privacy_release.add_argument("--path", help="Project directory to scan. Defaults to the current working directory")
    privacy_release.add_argument("--require-clean", action="store_true", help="Exit non-zero when release artifacts are found")
    privacy_release.set_defaults(func=cmd_privacy_release_audit)
    privacy_package = privacy_sub.add_parser("release-package", help="Write a public source ZIP excluding local runtime artifacts")
    privacy_package.add_argument("--source", help="Project directory to package. Defaults to the current working directory")
    privacy_package.add_argument("--output", required=True, help="Output ZIP path")
    privacy_package.set_defaults(func=cmd_privacy_release_package)

    chrome = sub.add_parser("chrome", help="Chrome automation profile")
    chrome_sub = chrome.add_subparsers(dest="chrome_command", required=True)
    chrome_launch = chrome_sub.add_parser("launch", help="Launch dedicated Chrome debugging profile")
    chrome_launch.add_argument("--port", type=int, default=9222)
    chrome_launch.add_argument("--address", default="127.0.0.1")
    chrome_launch.set_defaults(func=cmd_chrome_launch)

    server = sub.add_parser("serve", help="Serve local dashboard")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8787)
    server.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
