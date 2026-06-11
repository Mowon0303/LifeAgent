#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOME_DIR="${SENTINEL_RECORD_HOME:-$ROOT_DIR/.demo}"
PORT="${SENTINEL_RECORD_PORT:-8787}"
DURATION="${SENTINEL_RECORD_DURATION:-120}"
OUTPUT_DIR="${SENTINEL_RECORD_OUTPUT_DIR:-$ROOT_DIR/recordings}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
OUTPUT_FILE="${SENTINEL_RECORD_OUTPUT:-$OUTPUT_DIR/sentineldesk-demo-$TIMESTAMP.mov}"
AUDIO_FLAG="-g"
APPROVED="${SENTINEL_RECORD_APPROVED:-0}"
DRY_RUN="${SENTINEL_RECORD_DRY_RUN:-0}"

if [[ "${SENTINEL_RECORD_AUDIO:-1}" == "0" ]]; then
  AUDIO_FLAG=""
fi

if [[ "$APPROVED" != "1" && "$DRY_RUN" != "1" ]]; then
  if [[ ! -t 0 ]]; then
    echo "Refusing to start recording without explicit approval." >&2
    echo "Run interactively and type 'record', or set SENTINEL_RECORD_APPROVED=1 after reviewing the permission note." >&2
    exit 2
  fi
  echo "This will delete and recreate: $HOME_DIR"
  echo "It will start a local dashboard and use macOS screencapture to record the screen."
  echo "macOS may ask for screen and microphone permissions."
  read -r -p "Type 'record' to continue: " CONFIRMATION
  if [[ "$CONFIRMATION" != "record" ]]; then
    echo "Recording cancelled."
    exit 2
  fi
fi

mkdir -p "$OUTPUT_DIR"

cd "$ROOT_DIR"
rm -rf "$HOME_DIR"
python3 -m sentineldesk --home "$HOME_DIR" demo record-prep --port "$PORT"

if [[ "$DRY_RUN" == "1" ]]; then
  echo "Dry run complete. Recording not started."
  echo "Dashboard command: python3 -m sentineldesk --home $HOME_DIR serve --port $PORT"
  echo "Recording target would be: $OUTPUT_FILE"
  exit 0
fi

python3 -m sentineldesk --home "$HOME_DIR" serve --port "$PORT" &
SERVER_PID="$!"
cleanup() {
  kill "$SERVER_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

sleep 1
open "http://127.0.0.1:$PORT" >/dev/null 2>&1 || true

echo "Dashboard: http://127.0.0.1:$PORT"
echo "Recording target: $OUTPUT_FILE"
echo "Recording starts in 5 seconds. Grant macOS screen/audio permissions if prompted."
sleep 5

# shellcheck disable=SC2086
screencapture -v -V "$DURATION" -k $AUDIO_FLAG "$OUTPUT_FILE"
echo "Saved recording: $OUTPUT_FILE"
