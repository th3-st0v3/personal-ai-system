#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
    printf 'error: expected executable Python at %s/.venv/bin/python\n' "$REPO_ROOT" >&2
    exit 1
fi

mkdir -p "$REPO_ROOT/.runtime/overnight"
LOCK_FILE="$REPO_ROOT/.runtime/overnight/start.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    printf 'PASI overnight start is already in progress.\n'
    exit 1
fi

if [[ -f "$REPO_ROOT/.runtime/overnight/runner.pid" ]]; then
    pid="$(cat "$REPO_ROOT/.runtime/overnight/runner.pid" 2>/dev/null || true)"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
        printf 'PASI overnight runner is already active (PID %s).\n' "$pid"
        exit 0
    fi
    rm -f "$REPO_ROOT/.runtime/overnight/runner.pid"
fi

hours="${PASI_OVERNIGHT_HOURS:-12}"
log_file="$REPO_ROOT/.runtime/overnight/runner.log"

# Close the launcher's flock descriptor in the detached runner so the lock
# protects startup only and is not retained for the lifetime of the run.
nohup bash -c 'exec 9>&-; exec "$@"' _ "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/scripts/pasi_automation_entrypoint.py" --hours "$hours" "$@" >>"$log_file" 2>&1 < /dev/null &
pid=$!

printf 'Started PASI overnight runner (launcher PID %s, %s hours).\n' "$pid" "$hours"
printf 'Log: %s\n' "$log_file"
printf 'State: %s\n' "$REPO_ROOT/.runtime/overnight/state.json"
printf 'Action list: %s\n' "$REPO_ROOT/.runtime/automation/action-list.md"
printf 'Setup checklist: %s\n' "$REPO_ROOT/.runtime/automation/setup-requirements.md"
