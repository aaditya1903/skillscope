#!/usr/bin/env bash
# Capture the documentation screenshots from the running interface.
#
# Requires the API and the interface to already be running, so the images are
# always of the real application against a real corpus:
#
#   make serve
#   make frontend-dev
#   ./scripts/capture_screenshots.sh
set -euo pipefail

CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
FRONTEND="${FRONTEND_URL:-http://localhost:5173}"
OUTPUT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/docs/media"
WINDOW_SIZE="${WINDOW_SIZE:-1280,1100}"
PROFILE="$(mktemp -d "${TMPDIR:-/tmp}/skillscope-chrome.XXXXXX")"

trap 'rm -rf "$PROFILE"' EXIT

[[ -x "$CHROME" ]] || { echo "Chrome not found at $CHROME; set CHROME" >&2; exit 1; }
curl --fail --silent --output /dev/null "$FRONTEND/" \
  || { echo "the interface is not running at $FRONTEND" >&2; exit 1; }

mkdir -p "$OUTPUT"

run_chrome() {
  local name="$1" path="$2" output="$3"
  rm -f "$output"

  # Headless Chrome reliably writes the file but does not always exit, so wait
  # for the file rather than for the process.
  "$CHROME" \
    --headless \
    --disable-gpu \
    --no-first-run \
    --no-default-browser-check \
    --hide-scrollbars \
    --force-device-scale-factor=2 \
    --user-data-dir="$PROFILE/$name" \
    --window-size="$WINDOW_SIZE" \
    --virtual-time-budget=8000 \
    --screenshot="$output" \
    "$FRONTEND$path" >/dev/null 2>&1 &
  local chrome_pid=$!

  local size=0 previous=-1
  for _ in $(seq 1 60); do
    sleep 1
    [[ -f "$output" ]] || continue
    size=$(wc -c <"$output")
    # Stop once the file has stopped growing between polls.
    [[ "$size" -gt 0 && "$size" -eq "$previous" ]] && break
    previous=$size
  done

  kill -9 "$chrome_pid" 2>/dev/null || true
  wait "$chrome_pid" 2>/dev/null || true
  [[ -s "$output" ]]
}

capture() {
  local name="$1" path="$2" output="$OUTPUT/$1.png"
  echo "==> $name"
  # Chrome intermittently refuses to start straight after a previous headless
  # instance is killed, so one capture gets a second attempt.
  for attempt in 1 2 3; do
    if run_chrome "$name" "$path" "$output"; then
      return 0
    fi
    echo "    attempt $attempt failed; retrying" >&2
    sleep 3
  done
  echo "failed to capture $name" >&2
  exit 1
}

capture search "/#/search?q=create%20charts%20from%20a%20spreadsheet"
capture hybrid "/#/search?q=inspect%20a%20repository%20without%20changing%20it&mode=hybrid"
capture observatory "/#/observatory"

# The social preview is a static page rather than a view of the interface, so
# it renders at GitHub's exact card size from a local file.
FRONTEND="file://$OUTPUT" WINDOW_SIZE=1280,640 capture social-preview "/social-preview.html"

echo
echo "captured:"
ls -1 "$OUTPUT"/*.png
