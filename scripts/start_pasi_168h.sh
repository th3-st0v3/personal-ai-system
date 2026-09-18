#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Running Python files from scripts/ does not reliably put the repository root
# on sys.path. Export it here so the unattended launcher works from a clean
# shell without requiring a manually prepared PYTHONPATH.
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

PYTHON="$REPO_ROOT/.venv/bin/python"
RUNTIME_DIR="$REPO_ROOT/.runtime/overnight"
LOCK_FILE="$RUNTIME_DIR/start.lock"
RUNNER_PID_FILE="$RUNTIME_DIR/runner.pid"
BRIDGE_LOG="$RUNTIME_DIR/bridge.log"
CONTROLLER_LOG="$RUNTIME_DIR/controller-distribution.log"

if [[ ! -x "$PYTHON" ]]; then
    printf 'error: expected executable Python at %s\n' "$PYTHON" >&2
    exit 1
fi

hours="${PASI_OVERNIGHT_HOURS:-168}"
if [[ "$hours" != "168" && "$hours" != "168.0" ]]; then
    printf 'error: start_pasi_168h.sh is fixed to a 168-hour automation window; use start_pasi_overnight.sh for another duration.\n' >&2
    exit 2
fi

printf '=== PASI 168-HOUR AUTOMATION PREFLIGHT ===\n'
"$PYTHON" "$REPO_ROOT/scripts/pasi_setup.py" --check
printf '\n=== STARTING 168-HOUR RUN ===\n'

mkdir -p "$RUNTIME_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    printf 'PASI overnight start is already in progress.\n' >&2
    exit 1
fi

if [[ -f "$RUNNER_PID_FILE" ]]; then
    pid="$(cat "$RUNNER_PID_FILE" 2>/dev/null || true)"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
        printf 'PASI overnight runner is already active (PID %s).\n' "$pid"
        exit 0
    fi
    rm -f "$RUNNER_PID_FILE"
fi

# Each fresh run gets an isolated worktree and explicit branch. This prevents a
# stale dedicated worktree from being attached to a previous run's branch.
# Existing worktrees are never deleted by the launcher.
if [[ -n "${PASI_OVERNIGHT_WORKTREE:-}" ]]; then
    WORKTREE="$PASI_OVERNIGHT_WORKTREE"
else
    WORKTREE="$HOME/.pasi-worktrees/personal-ai-system-overnight-$(date -u +%Y%m%d-%H%M%S-%N)"
fi
BRANCH="${PASI_OVERNIGHT_BRANCH:-pasi/overnight-$(date -u +%Y%m%d-%H%M%S-%N)}"

if [[ -e "$WORKTREE" ]]; then
    printf 'error: selected fresh-run worktree path already exists: %s\n' "$WORKTREE" >&2
    printf 'Choose another PASI_OVERNIGHT_WORKTREE or remove/move that unrelated path manually.\n' >&2
    exit 3
fi

start_service() {
    local name="$1"
    local url="$2"
    local log_file="$3"
    shift 3

    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
        printf '%s: already healthy\n' "$name"
        return 0
    fi

    printf '%s: starting\n' "$name"
    # Close the launcher's flock descriptor in the child before exec. Without
    # this, long-lived services inherit fd 9 and keep start.lock held after the
    # launcher exits, falsely reporting that a run is still starting.
    nohup bash -c 'exec 9>&-; exec "$@"' _ env PYTHONPATH="$PYTHONPATH" "$PYTHON" "$REPO_ROOT/scripts/pasi_log_router.py" --log "$log_file" --max-bytes 2097152 --backups 4 -- "$@" < /dev/null &
}

# The direct PASI ChatGPT Controller 2.4.x talks to this localhost bridge.
# The Loader is not required when the direct controller is installed.
start_service \
    'PASI bridge' \
    'http://127.0.0.1:8765/health' \
    "$BRIDGE_LOG" \
    "$PYTHON" -m automation.orchestrator.bridge

start_service \
    'PASI controller distribution' \
    'http://127.0.0.1:8766/health' \
    "$CONTROLLER_LOG" \
    "$PYTHON" "$REPO_ROOT/scripts/pasi_controller_server.py"

service_deadline=$((SECONDS + 20))
while (( SECONDS < service_deadline )); do
    bridge_ok=0
    controller_ok=0
    curl -fsS --max-time 2 'http://127.0.0.1:8765/health' >/dev/null 2>&1 && bridge_ok=1 || true
    curl -fsS --max-time 2 'http://127.0.0.1:8766/health' >/dev/null 2>&1 && controller_ok=1 || true
    if (( bridge_ok == 1 && controller_ok == 1 )); then
        printf 'PASI local services: healthy\n'
        break
    fi
    sleep 1
done

if ! curl -fsS --max-time 2 'http://127.0.0.1:8765/health' >/dev/null 2>&1; then
    printf 'error: PASI bridge did not become healthy on 127.0.0.1:8765\n' >&2
    printf 'Bridge log: %s\n' "$BRIDGE_LOG" >&2
    exit 4
fi

if ! curl -fsS --max-time 2 'http://127.0.0.1:8766/health' >/dev/null 2>&1; then
    printf 'error: PASI controller distribution did not become healthy on 127.0.0.1:8766\n' >&2
    printf 'Controller log: %s\n' "$CONTROLLER_LOG" >&2
    exit 5
fi

log_file="$RUNTIME_DIR/runner.log"
# Close the launcher's flock descriptor in the detached runner as well so the
# lock protects startup only and is not retained for the lifetime of the run.
nohup bash -c 'exec 9>&-; exec "$@"' _ env PYTHONPATH="$PYTHONPATH" "$PYTHON" "$REPO_ROOT/scripts/pasi_log_router.py" --log "$log_file" --max-bytes 2097152 --backups 4 -- "$PYTHON" "$REPO_ROOT/scripts/pasi_extended_runtime_entrypoint.py" \
    --hours 168 \
    --worktree "$WORKTREE" \
    --branch "$BRANCH" \
    "$@" >>"$log_file" 2>&1 < /dev/null &
pid=$!

printf 'Started PASI extended runner (launcher PID %s, 168 hours).\n' "$pid"
printf 'Worktree: %s\n' "$WORKTREE"
printf 'Branch: %s\n' "$BRANCH"
printf 'Log: %s\n' "$log_file"
printf 'State: %s\n' "$RUNTIME_DIR/state.json"
printf 'Action list: %s\n' "$REPO_ROOT/.runtime/automation/action-list.md"
printf 'Setup checklist: %s\n' "$REPO_ROOT/.runtime/automation/setup-requirements.md"
