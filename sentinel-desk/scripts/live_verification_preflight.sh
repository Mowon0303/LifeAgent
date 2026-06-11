#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOME_DIR="${SENTINEL_LIVE_HOME:-$ROOT_DIR/.demo}"
PYTHON_BIN="${SENTINEL_LIVE_PYTHON:-$ROOT_DIR/.agent-venv/bin/python}"
ACCOUNT="${SENTINEL_LIVE_ACCOUNT:-user@example.com}"
GMAIL_QUERY="${SENTINEL_LIVE_GMAIL_QUERY:-deadline OR due}"

GOOGLE_CREDENTIALS_ENV="${SENTINEL_LIVE_GOOGLE_CREDENTIALS_ENV:-SENTINEL_GOOGLE_CREDENTIALS_JSON}"
GOOGLE_TOKEN_ENV="${SENTINEL_LIVE_GOOGLE_TOKEN_ENV:-SENTINEL_GOOGLE_TOKEN_JSON}"
APPLE_USER_ENV="${SENTINEL_LIVE_APPLE_USER_ENV:-SENTINEL_APPLE_ID}"
APPLE_PASSWORD_ENV="${SENTINEL_LIVE_APPLE_PASSWORD_ENV:-SENTINEL_APPLE_APP_PASSWORD}"

DRY_RUN="${SENTINEL_LIVE_DRY_RUN:-0}"
RUN_GOOGLE_TOKEN="${SENTINEL_LIVE_RUN_GOOGLE_TOKEN:-0}"
GOOGLE_TOKEN_NO_BROWSER="${SENTINEL_LIVE_GOOGLE_TOKEN_NO_BROWSER:-0}"
RUN_GMAIL_SYNC="${SENTINEL_LIVE_RUN_GMAIL_SYNC:-0}"
SEED_CALENDAR_DRAFT="${SENTINEL_LIVE_SEED_CALENDAR_DRAFT:-0}"
RUN_CALENDAR_WRITES="${SENTINEL_LIVE_RUN_CALENDAR_WRITES:-0}"
RUN_RELEASE_PACKAGE="${SENTINEL_LIVE_RUN_RELEASE_PACKAGE:-1}"
APPROVED="${SENTINEL_LIVE_APPROVED:-0}"
REQUIRE_READY="${SENTINEL_LIVE_REQUIRE_READY:-0}"
RELEASE_OUTPUT="${SENTINEL_LIVE_RELEASE_OUTPUT:-${TMPDIR:-/tmp}/sentineldesk.release.zip}"
RELEASE_EXTRACT_DIR="${SENTINEL_LIVE_RELEASE_EXTRACT_DIR:-}"

GOOGLE_CALENDAR_ID="${SENTINEL_LIVE_GOOGLE_CALENDAR_ID:-primary}"
APPLE_CALENDAR_ID="${SENTINEL_LIVE_APPLE_CALENDAR_ID:-default}"
GOOGLE_CONFIRMATION_ID="${SENTINEL_LIVE_GOOGLE_CONFIRMATION_ID:-live-google-sandbox-001}"
APPLE_CONFIRMATION_ID="${SENTINEL_LIVE_APPLE_CONFIRMATION_ID:-live-apple-sandbox-001}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
    echo "Using fallback Python runtime: $PYTHON_BIN" >&2
    echo "Install the project venv with: python3 -B -m venv .agent-venv && .agent-venv/bin/python -m pip install -e '.[agent,integrations]'" >&2
  else
    echo "No executable Python runtime found. Set SENTINEL_LIVE_PYTHON or create .agent-venv." >&2
    exit 2
  fi
fi

run_cmd() {
  echo "+ $*"
  if [[ "$DRY_RUN" == "1" ]]; then
    return 0
  fi
  "$@"
}

BASE_CMD=("$PYTHON_BIN" -B -m sentineldesk --home "$HOME_DIR")

echo "LifeAgent live verification preflight"
echo "Home: $HOME_DIR"
echo "Account: $ACCOUNT"
echo "Dry run: $DRY_RUN"
echo "Seed local verification calendar draft: $SEED_CALENDAR_DRAFT"
echo "External calendar writes enabled: $RUN_CALENDAR_WRITES"
echo "Source release package audit enabled: $RUN_RELEASE_PACKAGE"
echo "Final require-ready gate: $REQUIRE_READY"

cd "$ROOT_DIR"

run_cmd "${BASE_CMD[@]}" integrations env-template \
  --account "$ACCOUNT" \
  --google-credentials-env "$GOOGLE_CREDENTIALS_ENV" \
  --google-token-env "$GOOGLE_TOKEN_ENV" \
  --apple-user-env "$APPLE_USER_ENV" \
  --apple-password-env "$APPLE_PASSWORD_ENV"

if [[ "$RUN_GOOGLE_TOKEN" == "1" ]]; then
  TOKEN_CMD=("${BASE_CMD[@]}" integrations google-token \
    --credentials-env "$GOOGLE_CREDENTIALS_ENV" \
    --token-env "$GOOGLE_TOKEN_ENV")
  if [[ "$GOOGLE_TOKEN_NO_BROWSER" == "1" ]]; then
    TOKEN_CMD+=(--no-browser)
  fi
  run_cmd "${TOKEN_CMD[@]}"
  TOKEN_FILE="$HOME_DIR/secrets/google-token.json"
  if [[ "$DRY_RUN" != "1" && -f "$TOKEN_FILE" ]]; then
    export "$GOOGLE_TOKEN_ENV=$(cat "$TOKEN_FILE")"
    echo "Loaded Google token JSON from local token file into $GOOGLE_TOKEN_ENV for this script run."
  fi
else
  echo "Skipping Google OAuth token flow. Set SENTINEL_LIVE_RUN_GOOGLE_TOKEN=1 to run it."
fi

run_cmd "${BASE_CMD[@]}" integrations check \
  --suite all \
  --account "$ACCOUNT" \
  --google-credentials-env "$GOOGLE_CREDENTIALS_ENV" \
  --google-token-env "$GOOGLE_TOKEN_ENV" \
  --apple-user-env "$APPLE_USER_ENV" \
  --apple-password-env "$APPLE_PASSWORD_ENV" \
  --package

if [[ "$RUN_GMAIL_SYNC" == "1" ]]; then
  run_cmd "${BASE_CMD[@]}" email sync-gmail \
    --account "$ACCOUNT" \
    --query "$GMAIL_QUERY" \
    --credentials-env "$GOOGLE_CREDENTIALS_ENV" \
    --token-env "$GOOGLE_TOKEN_ENV"
else
  echo "Skipping Gmail sync. Set SENTINEL_LIVE_RUN_GMAIL_SYNC=1 after approving Gmail readonly access."
fi

if [[ "$SEED_CALENDAR_DRAFT" == "1" ]]; then
  run_cmd "${BASE_CMD[@]}" integrations seed-calendar-draft
else
  echo "Skipping local verification calendar draft seed. Set SENTINEL_LIVE_SEED_CALENDAR_DRAFT=1 if Gmail sync produced no deadline draft."
fi

if [[ "$RUN_CALENDAR_WRITES" == "1" ]]; then
  if [[ "$APPROVED" != "1" ]]; then
    echo "Refusing external calendar writes without SENTINEL_LIVE_APPROVED=1." >&2
    exit 2
  fi
  run_cmd "${BASE_CMD[@]}" calendar sync \
    --destination google \
    --account "$ACCOUNT" \
    --calendar-id "$GOOGLE_CALENDAR_ID"
  run_cmd "${BASE_CMD[@]}" calendar sync \
    --destination google \
    --account "$ACCOUNT" \
    --calendar-id "$GOOGLE_CALENDAR_ID" \
    --confirm \
    --confirmation-id "$GOOGLE_CONFIRMATION_ID" \
    --google-credentials-env "$GOOGLE_CREDENTIALS_ENV" \
    --google-token-env "$GOOGLE_TOKEN_ENV"
  run_cmd "${BASE_CMD[@]}" calendar sync \
    --destination apple \
    --account "$ACCOUNT" \
    --calendar-id "$APPLE_CALENDAR_ID"
  run_cmd "${BASE_CMD[@]}" calendar sync \
    --destination apple \
    --account "$ACCOUNT" \
    --calendar-id "$APPLE_CALENDAR_ID" \
    --confirm \
    --confirmation-id "$APPLE_CONFIRMATION_ID" \
    --apple-user-env "$APPLE_USER_ENV" \
    --apple-password-env "$APPLE_PASSWORD_ENV"
else
  echo "Skipping external calendar writes. Set SENTINEL_LIVE_RUN_CALENDAR_WRITES=1 and SENTINEL_LIVE_APPROVED=1 after reviewing draft events."
fi

FINAL_CMD=("${BASE_CMD[@]}" integrations check \
  --suite all \
  --account "$ACCOUNT" \
  --google-credentials-env "$GOOGLE_CREDENTIALS_ENV" \
  --google-token-env "$GOOGLE_TOKEN_ENV" \
  --apple-user-env "$APPLE_USER_ENV" \
  --apple-password-env "$APPLE_PASSWORD_ENV" \
  --package)
if [[ "$REQUIRE_READY" == "1" ]]; then
  FINAL_CMD+=(--require-ready)
fi

run_cmd "${FINAL_CMD[@]}"

COMPLETION_SOURCE_RELEASE_PATH="${RELEASE_EXTRACT_DIR:-/tmp/extracted-sentineldesk}"

if [[ "$RUN_RELEASE_PACKAGE" == "1" ]]; then
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "+ ${BASE_CMD[*]} privacy release-package --source $ROOT_DIR --output $RELEASE_OUTPUT"
    echo "+ mkdir -p $COMPLETION_SOURCE_RELEASE_PATH"
    echo "+ $PYTHON_BIN -B -m zipfile -e $RELEASE_OUTPUT $COMPLETION_SOURCE_RELEASE_PATH"
    echo "+ ${BASE_CMD[*]} privacy release-audit --path $COMPLETION_SOURCE_RELEASE_PATH --require-clean"
  else
    if [[ -z "$RELEASE_EXTRACT_DIR" ]]; then
      RELEASE_EXTRACT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sentineldesk-release-audit.XXXXXX")"
    else
      mkdir -p "$RELEASE_EXTRACT_DIR"
    fi
    COMPLETION_SOURCE_RELEASE_PATH="$RELEASE_EXTRACT_DIR"
    run_cmd "${BASE_CMD[@]}" privacy release-package \
      --source "$ROOT_DIR" \
      --output "$RELEASE_OUTPUT"
    "$PYTHON_BIN" -B -m zipfile -e "$RELEASE_OUTPUT" "$COMPLETION_SOURCE_RELEASE_PATH"
    "${BASE_CMD[@]}" privacy release-audit --path "$COMPLETION_SOURCE_RELEASE_PATH" --require-clean
  fi
else
  echo "Skipping source release package audit. Set SENTINEL_LIVE_RUN_RELEASE_PACKAGE=1 to run it."
fi

AUDIT_CMD=("${BASE_CMD[@]}" integrations completion-audit \
  --account "$ACCOUNT" \
  --google-credentials-env "$GOOGLE_CREDENTIALS_ENV" \
  --google-token-env "$GOOGLE_TOKEN_ENV" \
  --apple-user-env "$APPLE_USER_ENV" \
  --apple-password-env "$APPLE_PASSWORD_ENV" \
  --source-release-path "$COMPLETION_SOURCE_RELEASE_PATH")
if [[ "$REQUIRE_READY" == "1" ]]; then
  AUDIT_CMD+=(--require-ready)
fi

run_cmd "${AUDIT_CMD[@]}"

PRIVACY_CMD=("${BASE_CMD[@]}" privacy audit)
if [[ "$REQUIRE_READY" == "1" ]]; then
  PRIVACY_CMD+=(--require-clean)
fi

run_cmd "${PRIVACY_CMD[@]}"

echo "Live verification preflight finished. Use the latest redacted integration package and clean source release package after the privacy audits pass."
