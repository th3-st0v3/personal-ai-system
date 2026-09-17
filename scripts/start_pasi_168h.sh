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
WORKTREE="${PASI_OVERNIGHT_WORKTREE:-$HOME/.pasi-worktrees/personal-ai-system-overnight}"
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

# A fresh run gets a fresh branch. The dedicated overnight worktree can still
# be attached to the previous run's branch, so remove only that dedicated
# worktree before starting a non-resume run. The old Git branch is preserved.
resume_requested=0
for arg in "$@"; do
    if [[ "$arg" == "--resume" ]]; then
        resume_requested=1
        break
    fi
done

if (( resume_requested == 0 )); then
    if git worktree list --porcelain | awk -v wanted="$WORKTREE" '
        $1 == "worktree" && $2 == wanted { found = 1 }
        END { exit(found ? 0 : 1) }
    '; then
        printf 'Preparing dedicated overnight worktree for a fresh run: %s\n' "$WORKTREE"
        git worktree remove --force "$WORKTREE"
        git worktree prune
    elif [[ -e "$WORKTREE" ]]; then
        printf 'error: overnight worktree path exists but is not a registered Git worktree: %s\n' "$WORKTREE" >&2
        printf 'Move that unrelated directory aside, then retry. It was not removed automatically.\n' >&2
        exit 3
    fi
fi

# The direct PASI ChatGPT Controller 2.4.3 talks to the localhost bridge on
# 8765. Start required local services before the background runner so a dead
# bridge cannot produce a misleading "runner started" state.
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
    nohup env PYTHONPATH="$PYTHONPATH" "$@" >>"$log_file" 2>&1 < /dev/null &
}

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
nohup env PYTHONPATH="$PYTHONPATH" "$PYTHON" "$REPO_ROOT/scripts/pasi_extended_runtime_entrypoint.py" --hours 168 "$@" >>"$log_file" 2>&1 < /dev/null &
pid=$!

printf 'Started PASI extended runner (launcher PID %s, 168 hours).\n' "$pid"
printf 'Log: %s\n' "$log_file"
printf 'State: %s\n' "$RUNTIME_DIR/state.json"
printf 'Action list: %s\n' "$REPO_ROOT/.runtime/automation/action-list.md"
printf 'Setup checklist: %s\n' "$REPO_ROOT/.runtime/automation/setup-requirements.md"
