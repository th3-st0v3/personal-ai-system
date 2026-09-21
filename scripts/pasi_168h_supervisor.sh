#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="$REPO_ROOT/.venv/bin/python"
RUNTIME_DIR="$REPO_ROOT/.runtime/overnight"
SUPERVISOR_PID_FILE="$RUNTIME_DIR/supervisor.pid"
RUNNER_PID_FILE="$RUNTIME_DIR/runner.pid"
STOP_FILE="$RUNTIME_DIR/supervisor.stop"
MAX_RESTARTS="${PASI_SUPERVISOR_MAX_RESTARTS:-8}"
RESET_AFTER_SECONDS="${PASI_SUPERVISOR_RESET_AFTER_SECONDS:-60}"
BASE_BACKOFF_SECONDS="${PASI_SUPERVISOR_BACKOFF_SECONDS:-5}"
MAX_BACKOFF_SECONDS="${PASI_SUPERVISOR_MAX_BACKOFF_SECONDS:-120}"

hours="168"
worktree=""
branch=""
passthrough=()
while (($#)); do
    case "$1" in
        --hours)
            [[ $# -ge 2 ]] || { printf 'error: --hours requires a value\n' >&2; exit 2; }
            hours="$2"
            shift 2
            ;;
        --worktree)
            [[ $# -ge 2 ]] || { printf 'error: --worktree requires a value\n' >&2; exit 2; }
            worktree="$2"
            shift 2
            ;;
        --branch)
            [[ $# -ge 2 ]] || { printf 'error: --branch requires a value\n' >&2; exit 2; }
            branch="$2"
            shift 2
            ;;
        --)
            shift
            passthrough+=( "$@" )
            break
            ;;
        *)
            passthrough+=( "$1" )
            shift
            ;;
    esac
done

[[ "$hours" == "168" || "$hours" == "168.0" ]] || {
    printf 'error: supervisor is fixed to a 168-hour runtime window\n' >&2
    exit 2
}
[[ -x "$PYTHON" ]] || {
    printf 'error: expected executable Python at %s\n' "$PYTHON" >&2
    exit 1
}
[[ -n "$worktree" && -n "$branch" ]] || {
    printf 'error: supervisor requires --worktree and --branch\n' >&2
    exit 2
}
mkdir -p "$RUNTIME_DIR"

if [[ -f "$SUPERVISOR_PID_FILE" ]]; then
    existing="$(cat "$SUPERVISOR_PID_FILE" 2>/dev/null || true)"
    if [[ "$existing" =~ ^[0-9]+$ ]] && kill -0 "$existing" 2>/dev/null && [[ "$existing" != "$$" ]]; then
        printf 'PASI 168-hour supervisor is already active (PID %s).\n' "$existing" >&2
        exit 0
    fi
fi

printf '%s\n' "$$" > "$SUPERVISOR_PID_FILE"
rm -f "$STOP_FILE"

cleanup() {
    if [[ -f "$SUPERVISOR_PID_FILE" ]] && [[ "$(cat "$SUPERVISOR_PID_FILE" 2>/dev/null || true)" == "$$" ]]; then
        rm -f "$SUPERVISOR_PID_FILE"
    fi
}
trap cleanup EXIT
trap 'touch "$STOP_FILE"; exit 0' INT TERM

state_deadline_reached() {
    [[ -f "$RUNTIME_DIR/state.json" ]] || return 1
    "$PYTHON" - "$RUNTIME_DIR/state.json" <<'PY'
import json
import sys
from datetime import datetime, timezone

try:
    state = json.loads(open(sys.argv[1], encoding="utf-8").read())
    deadline = datetime.fromisoformat(str(state["deadline_at"]).replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    raise SystemExit(0 if now >= deadline else 1)
except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
    raise SystemExit(1)
PY
}

state_is_terminal() {
    [[ -f "$RUNTIME_DIR/state.json" ]] || return 1
    "$PYTHON" - "$RUNTIME_DIR/state.json" <<'PY'
import json
import sys

try:
    state = json.loads(open(sys.argv[1], encoding="utf-8").read())
    reason = str(state.get("stop_reason", "")).strip().casefold()
    raise SystemExit(0 if reason in {"deadline_reached", "stopped"} else 1)
except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
    raise SystemExit(1)
PY
}

log_supervisor() {
    printf '[PASI supervisor] %s\n' "$*" >&2
}

runner_cmd_matches() {
    local pid="$1"
    local command_line
    command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
    [[ "$command_line" == *"pasi_extended_runtime_entrypoint.py"* ]] &&
        [[ "$command_line" == *"--hours 168"* ]] &&
        [[ "$command_line" == *"--worktree $worktree"* ]] &&
        [[ "$command_line" == *"--branch $branch"* ]]
}

adopted_runner_pid=""
if [[ -f "$RUNNER_PID_FILE" ]]; then
    candidate="$(cat "$RUNNER_PID_FILE" 2>/dev/null || true)"
    if [[ "$candidate" =~ ^[0-9]+$ ]] && kill -0 "$candidate" 2>/dev/null; then
        if runner_cmd_matches "$candidate"; then
            adopted_runner_pid="$candidate"
            log_supervisor "adopting already-running engine PID $candidate after supervisor restart"
        else
            log_supervisor "runner PID $candidate is live but does not match the requested worktree/branch; refusing to supervise it"
            exit 3
        fi
    else
        rm -f "$RUNNER_PID_FILE"
    fi
fi

restart_count=0
backoff="$BASE_BACKOFF_SECONDS"
resume=0

while true; do
    if [[ -f "$STOP_FILE" ]] || state_deadline_reached || state_is_terminal; then
        exit 0
    fi

    started_at="$(date +%s)"
    if [[ -n "$adopted_runner_pid" ]]; then
        log_supervisor "monitoring adopted engine PID $adopted_runner_pid"
        set +e
        while kill -0 "$adopted_runner_pid" 2>/dev/null; do
            if [[ -f "$STOP_FILE" ]] || state_deadline_reached || state_is_terminal; then
                exit 0
            fi
            sleep 5
        done
        code=0
        set -e
        adopted_runner_pid=""
    else
        cmd=(
            "$PYTHON"
            "$REPO_ROOT/scripts/pasi_extended_runtime_entrypoint.py"
            --hours "$hours"
            --worktree "$worktree"
            --branch "$branch"
        )
        if (( resume == 1 )); then
            cmd+=(--resume)
        fi
        cmd+=( "${passthrough[@]}" )

        log_supervisor "starting engine (resume=$resume, restart_count=$restart_count)"
        set +e
        "${cmd[@]}"
        code=$?
        set -e
    fi
    finished_at="$(date +%s)"
    runtime_seconds=$((finished_at - started_at))

    if [[ -f "$STOP_FILE" ]] || state_deadline_reached || state_is_terminal; then
        exit 0
    fi

    if (( runtime_seconds >= RESET_AFTER_SECONDS )); then
        restart_count=0
        backoff="$BASE_BACKOFF_SECONDS"
    else
        restart_count=$((restart_count + 1))
    fi

    if (( restart_count > MAX_RESTARTS )); then
        log_supervisor "restart budget exhausted after $MAX_RESTARTS rapid engine exits; durable state remains for manual recovery"
        exit 1
    fi

    log_supervisor "engine exited code=$code after ${runtime_seconds}s; resuming in ${backoff}s"
    sleep "$backoff"
    next=$((backoff * 2))
    if (( next > MAX_BACKOFF_SECONDS )); then
        backoff="$MAX_BACKOFF_SECONDS"
    else
        backoff="$next"
    fi
    resume=1
done
