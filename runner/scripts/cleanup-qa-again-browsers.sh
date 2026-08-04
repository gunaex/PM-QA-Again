#!/usr/bin/env bash
# Lists (and optionally terminates) orphaned QA-Again-owned Chromium
# processes on macOS/Linux.
#
# QA-Again's runner/recorder/verification code (see
# runner/src/browser/browserRun.ts and runner/scripts/lib/browserLifecycle.mjs)
# launches every headed Chromium instance with its own uniquely-named
# profile directory under the OS temp folder, prefixed
# "qa-again-playwright-". This script finds chrome/chromium processes
# whose command line references such a profile directory. It NEVER
# matches or terminates a process that does not reference one of these
# profile directories -- a tester's normal browser session is always
# left alone (plain `pkill chrome` is exactly what this script refuses
# to do).
#
# Usage:
#   ./cleanup-qa-again-browsers.sh                 # list only (default, safe)
#   ./cleanup-qa-again-browsers.sh --kill           # list, terminate, clean up
#   ./cleanup-qa-again-browsers.sh --kill --older-than 10   # only if >10 min old

set -euo pipefail

PROFILE_MARKER="qa-again-playwright-"
KILL=0
OLDER_THAN_MIN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kill) KILL=1; shift ;;
    --older-than) OLDER_THAN_MIN="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# ps output: PID, elapsed time (etimes, in seconds), full command line
MATCHES=$(ps -eo pid,etimes,command | grep -- "$PROFILE_MARKER" | grep -v grep || true)

if [[ -z "$MATCHES" ]]; then
  echo "No QA-Again-owned Chromium processes found (matched by profile-dir prefix '$PROFILE_MARKER')."
  exit 0
fi

echo "Found QA-Again-owned Chromium process(es):"
echo "$MATCHES" | while read -r pid etimes cmd; do
  profile_dir=$(echo "$cmd" | grep -oE -- "--user-data-dir=[^ ]+" | sed 's/--user-data-dir=//' || true)
  echo "  PID $pid  age=$((etimes / 60))min  profile=${profile_dir:-unknown}"
done

if [[ "$KILL" -ne 1 ]]; then
  echo ""
  echo "Read-only mode (default) -- pass --kill to terminate these and remove their profile directories."
  exit 0
fi

echo ""
echo "Terminating eligible process(es) and removing their profile directories..."
OLDER_THAN_SEC=$((OLDER_THAN_MIN * 60))

echo "$MATCHES" | while read -r pid etimes cmd; do
  if [[ "$etimes" -lt "$OLDER_THAN_SEC" ]]; then
    continue
  fi
  profile_dir=$(echo "$cmd" | grep -oE -- "--user-data-dir=[^ ]+" | sed 's/--user-data-dir=//' || true)
  if kill -9 "$pid" 2>/dev/null; then
    echo "  Killed PID $pid"
  else
    echo "  Could not kill PID $pid (already gone?)"
  fi
  if [[ -n "${profile_dir:-}" && -d "$profile_dir" ]]; then
    rm -rf "$profile_dir"
    echo "  Removed profile dir $profile_dir"
  fi
done

# Sweep the registry dir for stale bookkeeping entries whose profile
# directory no longer exists.
REGISTRY_DIR="${TMPDIR:-/tmp}/qa-again-playwright-registry"
if [[ -d "$REGISTRY_DIR" ]]; then
  for f in "$REGISTRY_DIR"/*.json; do
    [[ -e "$f" ]] || continue
    dir=$(grep -oE '"userDataDir"\s*:\s*"[^"]+"' "$f" | sed -E 's/.*:\s*"(.*)"/\1/' || true)
    if [[ -n "$dir" && ! -d "$dir" ]]; then
      rm -f "$f"
    fi
  done
fi

echo "Done."
