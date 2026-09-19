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
START_PID_FILE="$REPO_ROOT/.runtime/overnight/start.pid"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    if [[ -f "$START_PID_FILE" ]]; then
        start_pid="$(cat "$START_PID_FILE" 2>/dev/null || true)"
        if [[ "$start_pid" =~ ^[0-9]+$ ]] && kill -0 "$start_pid" 2>/dev/null; then
            printf 'PASI overnight start is already in progress (launcher PID %s).\n' "$start_pid"
        else
            rm -f "$START_PID_FILE"
            printf 'PASI overnight start lock is currently held, but its launcher PID is stale or missing.\n'
        fi
    else
        printf 'PASI overnight start lock is currently held by another launcher.\n'
    fi
    exit 1
fi

printf '%s\n' "$$" > "$START_PID_FILE"
cleanup_start_pid() {
    if [[ -f "$START_PID_FILE" ]] && [[ "$(cat "$START_PID_FILE" 2>/dev/null || true)" == "$$" ]]; then
        rm -f "$START_PID_FILE"
    fi
}
trap cleanup_start_pid EXIT

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
nohup bash -c 'exec 9>&-; exec "$@"' _ "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/scripts/pasi_log_router.py" --log "$log_file" --max-bytes 2097152 --backups 4 -- "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/scripts/pasi_automation_entrypoint.py" --hours "$hours" "$@" < /dev/null &
pid=$!

printf 'Started PASI overnight runner (launcher PID %s, %s hours).\n' "$pid" "$hours"
printf 'Log: %s\n' "$log_file"
printf 'State: %s\n' "$REPO_ROOT/.runtime/overnight/state.json"
printf 'Action list: %s\n' "$REPO_ROOT/.runtime/automation/action-list.md"
printf 'Setup checklist: %s\n' "$REPO_ROOT/.runtime/automation/setup-requirements.md"
