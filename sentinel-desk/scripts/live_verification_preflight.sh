#!/usr/bin/env bash
# Thin wrapper. The preflight itself lives in
# sentineldesk/integrations/live_verification/preflight.py so Windows can run
# the identical sequence without Bash:
#
#   PowerShell:  .\scripts\live_verification_preflight.ps1
#   Any shell:   python -B -m sentineldesk integrations preflight
#
# All SENTINEL_LIVE_* environment variables behave exactly as before.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${SENTINEL_LIVE_PYTHON:-$ROOT_DIR/.agent-venv/bin/python}"

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

export SENTINEL_LIVE_PYTHON="$PYTHON_BIN"
cd "$ROOT_DIR"
exec "$PYTHON_BIN" -B -m sentineldesk integrations preflight
