#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Running Python files from scripts/ does not reliably put the repository root
# on sys.path. Export it here so the unattended launcher works from a clean
# shell without requiring a manually prepared PYTHONPATH.
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PASI_LOCAL_GATE_MODE="${PASI_LOCAL_GATE_MODE:-fast}"

PYTHON="$REPO_ROOT/.venv/bin/python"
RUNTIME_DIR="$REPO_ROOT/.runtime/overnight"
LOCK_FILE="$RUNTIME_DIR/start.lock"
RUNNER_PID_FILE="$RUNTIME_DIR/runner.pid"
START_PID_FILE="$RUNTIME_DIR/start.pid"
BRIDGE_LOG="$RUNTIME_DIR/bridge.log"
CONTROLLER_LOG="$RUNTIME_DIR/controller-distribution.log"
BRIDGE_PID_FILE="$RUNTIME_DIR/bridge.pid"
CONTROLLER_PID_FILE="$RUNTIME_DIR/controller-distribution.pid"

if [[ ! -x "$PYTHON" ]]; then
    printf 'error: expected executable Python at %s\n' "$PYTHON" >&2
    exit 1
fi

hours="${PASI_OVERNIGHT_HOURS:-168}"
if [[ "$hours" != "168" && "$hours" != "168.0" ]]; then
    printf 'error: start_pasi_168h.sh is fixed to a 168-hour automation window; use start_pasi_overnight.sh for another duration.\n' >&2
    exit 2
fi

TOKEN_FILE="$HOME/.pasi/bridge-token"
EXTENSION_TOKEN_FILE="$REPO_ROOT/automation/chromium/pasi-chatgpt/.bridge-token"
mkdir -p "$HOME/.pasi"
bridge_already_healthy=0
if curl -fsS --max-time 3 'http://127.0.0.1:8765/health' >/dev/null 2>&1; then
    bridge_already_healthy=1
fi
if (( bridge_already_healthy == 0 )); then
    "$PYTHON" - <<'PY' > "$TOKEN_FILE"
import secrets
print(secrets.token_urlsafe(48))
PY
    chmod 600 "$TOKEN_FILE"
elif [[ ! -s "$TOKEN_FILE" ]]; then
    printf 'error: bridge is already healthy but its managed token file is missing; stop the bridge and restart via this launcher.\n' >&2
    exit 3
fi
cp "$TOKEN_FILE" "$EXTENSION_TOKEN_FILE"
chmod 600 "$EXTENSION_TOKEN_FILE"
export PASI_BRIDGE_TOKEN="$(cat "$TOKEN_FILE")"

printf '=== PASI 168-HOUR AUTOMATION PREFLIGHT ===\n'
printf 'Local validation mode: %s\n' "$PASI_LOCAL_GATE_MODE"
"$PYTHON" "$REPO_ROOT/scripts/pasi_setup.py" --check
printf '\n=== STARTING 168-HOUR RUN ===\n'

mkdir -p "$RUNTIME_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    if [[ -f "$START_PID_FILE" ]]; then
        start_pid="$(cat "$START_PID_FILE" 2>/dev/null || true)"
        if [[ "$start_pid" =~ ^[0-9]+$ ]] && kill -0 "$start_pid" 2>/dev/null; then
            printf 'PASI overnight start is already in progress (launcher PID %s).\n' "$start_pid" >&2
        else
            rm -f "$START_PID_FILE"
            printf 'PASI overnight start lock is currently held, but its launcher PID is stale or missing.\n' >&2
        fi
    else
        printf 'PASI overnight start lock is currently held by another launcher.\n' >&2
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

if [[ -f "$RUNNER_PID_FILE" ]]; then
    pid="$(cat "$RUNNER_PID_FILE" 2>/dev/null || true)"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
        printf 'PASI overnight runner is already active (PID %s).\n' "$pid"
        exit 0
    fi
    rm -f "$RUNNER_PID_FILE"
fi

# Each run is isolated, but the consolidated branch may already be attached
# to a dedicated worktree left by an earlier run. Reuse that exact worktree
# when it is registered to the requested branch; never force-reset or delete
# an existing worktree from this launcher.
requested_branch="${PASI_OVERNIGHT_BRANCH:-}"
configured_worktree="${PASI_OVERNIGHT_WORKTREE:-}"
run_stamp="$(date -u +%Y%m%d-%H%M%S-%N)"
BRANCH="${requested_branch:-pasi/overnight-$run_stamp}"
WORKTREE=""
REUSE_EXISTING_WORKTREE=0

worktree_for_branch() {
    local target="$1"
    local path=""
    local current_branch=""
    local line
    while IFS= read -r line || [[ -n "$line" ]]; do
        case "$line" in
            "worktree "*) path="${line#worktree }" ;;
            "branch refs/heads/"*) current_branch="${line#branch refs/heads/}" ;;
            "")
                if [[ "$current_branch" == "$target" ]]; then
                    printf '%s\n' "$path"
                    return 0
                fi
                path=""
                current_branch=""
                ;;
        esac
    done < <(git worktree list --porcelain)
    if [[ "$current_branch" == "$target" ]]; then
        printf '%s\n' "$path"
    fi
}

if [[ -n "$configured_worktree" ]]; then
    WORKTREE="$(realpath -m -- "$configured_worktree")"
    if [[ ! -d "$WORKTREE" || ( ! -f "$WORKTREE/.git" && ! -d "$WORKTREE/.git" ) ]]; then
        printf 'error: PASI_OVERNIGHT_WORKTREE is not an existing git worktree: %s\n' "$WORKTREE" >&2
        exit 3
    fi
    actual_branch="$(git -C "$WORKTREE" branch --show-current 2>/dev/null || true)"
    if [[ -n "$requested_branch" && "$actual_branch" != "$requested_branch" ]]; then
        printf 'error: PASI_OVERNIGHT_WORKTREE is on %s, not requested branch %s.\n' "${actual_branch:-detached}" "$requested_branch" >&2
        exit 3
    fi
    [[ -n "$actual_branch" ]] && BRANCH="$actual_branch"
    REUSE_EXISTING_WORKTREE=1
elif [[ -n "$requested_branch" ]]; then
    existing_worktree="$(worktree_for_branch "$requested_branch")"
    if [[ -n "$existing_worktree" ]]; then
        WORKTREE="$existing_worktree"
        BRANCH="$requested_branch"
        REUSE_EXISTING_WORKTREE=1
    else
        WORKTREE="$HOME/.pasi-worktrees/personal-ai-system-overnight-$run_stamp"
    fi
else
    WORKTREE="$HOME/.pasi-worktrees/personal-ai-system-overnight-$run_stamp"
fi

if (( REUSE_EXISTING_WORKTREE == 1 )); then
    worktree_status="$(git -C "$WORKTREE" status --porcelain --untracked-files=all 2>/dev/null || true)"
    if [[ -n "$worktree_status" ]]; then
        printf 'error: selected existing PASI worktree is dirty; preserve or stash its local changes before starting the 168-hour runner.\n' >&2
        printf 'Worktree: %s\n' "$WORKTREE" >&2
        printf '%s\n' "$worktree_status" >&2
        exit 3
    fi

    # The dedicated worktree may have been left behind by an earlier run.
    # Bring it to the latest remote branch without overwriting any local commits.
    if git show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
        if ! git -C "$WORKTREE" merge-base --is-ancestor "$BRANCH" "origin/$BRANCH" 2>/dev/null; then
            if ! git -C "$WORKTREE" merge-base --is-ancestor "origin/$BRANCH" "$BRANCH" 2>/dev/null; then
                printf 'error: existing PASI worktree branch %s has diverged from origin/%s; refusing to overwrite it.\n' "$BRANCH" "$BRANCH" >&2
                exit 3
            fi
        else
            git -C "$WORKTREE" merge --ff-only "origin/$BRANCH"
        fi
    fi
else
    if [[ -e "$WORKTREE" ]]; then
        printf 'error: selected fresh-run worktree path already exists: %s\n' "$WORKTREE" >&2
        printf 'Choose another PASI_OVERNIGHT_WORKTREE or remove/move that unrelated path manually.\n' >&2
        exit 3
    fi
fi

# When a caller names an existing consolidated branch, use it as the isolated
# run's source ref when the runner needs to create a new worktree.
if [[ -z "${PASI_OVERNIGHT_BASE_REF:-}" && -n "$requested_branch" ]] &&
   git show-ref --verify --quiet "refs/remotes/origin/$requested_branch"; then
    export PASI_OVERNIGHT_BASE_REF="origin/$requested_branch"
fi

start_service() {
    local name="$1"
    local url="$2"
    local log_file="$3"
    local pid_file="$4"
    shift 4

    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
        printf '%s: already healthy\n' "$name"
        return 0
    fi

    printf '%s: starting\n' "$name"
    # Close the launcher's flock descriptor in the child before exec. Without
    # this, long-lived services inherit fd 9 and keep start.lock held after the
    # launcher exits, falsely reporting that a run is still starting.
    nohup bash -c 'exec 9>&-; exec "$@"' _ env PYTHONPATH="$PYTHONPATH" "$PYTHON" "$REPO_ROOT/scripts/pasi_log_router.py" --log "$log_file" --max-bytes 1048576 --backups 2 -- "$@" < /dev/null &
    local service_pid=$!
    printf '%s\n' "$service_pid" > "$pid_file"
}

# The direct PASI ChatGPT Controller 2.4.x talks to this localhost bridge.
# The Loader is not required when the direct controller is installed.
start_service \
    'PASI bridge' \
    'http://127.0.0.1:8765/health' \
    "$BRIDGE_LOG" \
    "$BRIDGE_PID_FILE" \
    "$PYTHON" -m automation.orchestrator.bridge

start_service \
    'PASI controller distribution' \
    'http://127.0.0.1:8766/health' \
    "$CONTROLLER_LOG" \
    "$CONTROLLER_PID_FILE" \
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

browser_observation_ready() {
    "$PYTHON" - <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

root = Path.cwd()
manifest_path = root / "automation" / "tampermonkey" / "controller-sync.json"
try:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_version = manifest.get("version")
    token = (os.environ.get("PASI_BRIDGE_TOKEN", "") or (Path.home() / ".pasi" / "bridge-token").read_text(encoding="utf-8")).strip()
    request = urllib.request.Request(
        "http://127.0.0.1:8765/browser/observation",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=3.0) as response:
        payload = json.loads(response.read(2_000_000).decode("utf-8"))
except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError):
    raise SystemExit(1)

observation = payload.get("observation") if isinstance(payload, dict) else None
data = observation.get("data") if isinstance(observation, dict) and isinstance(observation.get("data"), dict) else observation
if not isinstance(data, dict):
    raise SystemExit(1)

kind = data.get("kind")
actual_version = data.get("controller_version")
if kind not in {"chatgpt_health", "chatgpt_state"}:
    raise SystemExit(1)
if not isinstance(expected_version, str) or not expected_version.strip() or actual_version != expected_version.strip():
    raise SystemExit(1)
if data.get("auth_required") is True:
    raise SystemExit(2)
raise SystemExit(0)
PY
}

printf '
=== VERIFYING NATIVE CHATGPT BROWSER ===
'
browser_deadline=$((SECONDS + 30))
browser_ready=0
browser_auth_required=0
while (( SECONDS < browser_deadline )); do
    if browser_observation_ready; then
        browser_ready=1
        break
    else
        status=$?
        if (( status == 2 )); then
            browser_auth_required=1
            break
        fi
    fi
    sleep 1
done

if (( browser_auth_required == 1 )); then
    printf 'error: the native PASI ChatGPT extension is reporting that authentication/security verification is required. Complete it in the browser, then restart the launcher.\n' >&2
    exit 7
fi

if (( browser_ready == 0 )); then
    printf 'error: native PASI ChatGPT browser heartbeat was not verified within 30 seconds.\n' >&2
    printf 'Open https://chatgpt.com/ in the Chromium browser with PASI ChatGPT Controller enabled and reload the extension.\n' >&2
    printf 'Browser observation endpoint: http://127.0.0.1:8765/browser/observation\n' >&2
    exit 8
fi

printf 'Native PASI ChatGPT browser: healthy and controller-compatible\n'

log_file="$RUNTIME_DIR/runner.log"
# Close the launcher's flock descriptor in the detached runner as well so the
# lock protects startup only and is not retained for the lifetime of the run.
nohup bash -c 'exec 9>&-; exec "$@"' _ env PYTHONPATH="$PYTHONPATH" "$PYTHON" "$REPO_ROOT/scripts/pasi_log_router.py" --log "$log_file" --max-bytes 2097152 --backups 4 -- "$PYTHON" "$REPO_ROOT/scripts/pasi_extended_runtime_entrypoint.py" \
    --hours 168 \
    --worktree "$WORKTREE" \
    --branch "$BRANCH" \
    "$@" < /dev/null &
pid=$!

# Do not report a successful start until the detached runner has actually
# acquired its runtime lock and written a live runner PID. This catches an
# immediate startup failure from the Start path instead of leaving the user
# with a misleading "started" message.
runner_start_deadline=$((SECONDS + 15))
runner_ready=0
while (( SECONDS < runner_start_deadline )); do
    if [[ -f "$RUNNER_PID_FILE" ]]; then
        runner_pid="$(cat "$RUNNER_PID_FILE" 2>/dev/null || true)"
        if [[ "$runner_pid" =~ ^[0-9]+$ ]] && kill -0 "$runner_pid" 2>/dev/null; then
            runner_ready=1
            break
        fi
    fi
    sleep 1
done

if (( runner_ready == 0 )); then
    printf 'error: detached PASI runner did not become live within the startup verification window.\n' >&2
    printf 'Runner log: %s\n' "$log_file" >&2
    exit 6
fi

printf 'Started PASI extended runner (launcher PID %s, runner PID %s, 168 hours).\n' "$pid" "$runner_pid"
printf 'Worktree: %s\n' "$WORKTREE"
printf 'Branch: %s\n' "$BRANCH"
printf 'Log: %s\n' "$log_file"
printf 'State: %s\n' "$RUNTIME_DIR/state.json"
printf 'Action list: %s\n' "$REPO_ROOT/.runtime/automation/action-list.md"
printf 'Setup checklist: %s\n' "$REPO_ROOT/.runtime/automation/setup-requirements.md"
