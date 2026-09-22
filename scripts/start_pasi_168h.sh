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
export PASI_RUNTIME_DIR="${PASI_RUNTIME_DIR:-$HOME/.pasi/overnight}"
export PASI_ROADMAP_PATH="${PASI_ROADMAP_PATH:-$REPO_ROOT/roadmaps/pasi-default.json}"

# The launcher owns --roadmap so it can validate the exact selected file before
# the detached supervisor starts. All other arguments pass through unchanged.
launcher_args=()
while (( $# )); do
    case "$1" in
        --roadmap)
            [[ $# -ge 2 ]] || { printf 'error: --roadmap requires a path\n' >&2; exit 2; }
            PASI_ROADMAP_PATH="$2"
            shift 2
            ;;
        *)
            launcher_args+=( "$1" )
            shift
            ;;
    esac
done
export PASI_ROADMAP_PATH

PASI_VENV="${PASI_VENV:-$HOME/.pasi/venv}"
if [[ -n "${PASI_PYTHON:-}" ]]; then
    PYTHON="$PASI_PYTHON"
elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    PYTHON="$REPO_ROOT/.venv/bin/python"
else
    PYTHON="$PASI_VENV/bin/python"
    if [[ ! -x "$PYTHON" ]]; then
        if ! command -v python3 >/dev/null 2>&1; then
            printf 'error: python3 is required to create the persistent PASI environment at %s\n' "$PASI_VENV" >&2
            exit 1
        fi
        mkdir -p "$(dirname -- "$PASI_VENV")"
        printf 'PASI Python environment: creating %s\n' "$PASI_VENV"
        python3 -m venv "$PASI_VENV" || {
            printf 'error: failed to create persistent PASI Python environment at %s\n' "$PASI_VENV" >&2
            exit 1
        }
    fi
    printf 'PASI Python environment: using persistent %s\n' "$PASI_VENV"
    "$PYTHON" -m pip install --disable-pip-version-check --requirement "$REPO_ROOT/requirements.txt" >/dev/null
    if [[ -f "$REPO_ROOT/requirements-dev.txt" ]]; then
        "$PYTHON" -m pip install --disable-pip-version-check --requirement "$REPO_ROOT/requirements-dev.txt" >/dev/null
    fi
fi

if [[ ! -x "$PYTHON" ]]; then
    printf 'error: expected executable Python at %s\n' "$PYTHON" >&2
    exit 1
fi
export PASI_PYTHON="$PYTHON"

RUNTIME_DIR="${PASI_RUNTIME_DIR:-$HOME/.pasi/overnight}"
LOCK_FILE="$RUNTIME_DIR/start.lock"
RUNNER_PID_FILE="$RUNTIME_DIR/runner.pid"
START_PID_FILE="$RUNTIME_DIR/start.pid"
BRIDGE_LOG="$RUNTIME_DIR/bridge.log"
BRIDGE_PID_FILE="$RUNTIME_DIR/bridge.pid"
SUPERVISOR_PID_FILE="$RUNTIME_DIR/supervisor.pid"
STATE_FILE="$RUNTIME_DIR/state.json"

if [[ ! -x "$PYTHON" ]]; then
    printf 'error: expected executable Python at %s\n' "$PYTHON" >&2
    exit 1
fi

hours="${PASI_OVERNIGHT_HOURS:-168}"
if [[ "$hours" != "168" && "$hours" != "168.0" ]]; then
    printf 'error: start_pasi_168h.sh is fixed to a 168-hour automation window; use start_pasi_overnight.sh for another duration.\n' >&2
    exit 2
fi

ROADMAP_PATH="$(realpath -m -- "$PASI_ROADMAP_PATH")"
if [[ ! -f "$ROADMAP_PATH" ]]; then
    printf 'error: PASI roadmap does not exist: %s\n' "$ROADMAP_PATH" >&2
    exit 3
fi
"$PYTHON" - "$ROADMAP_PATH" <<'PY'
import sys
from pathlib import Path

from scripts.pasi_hybrid_planner import PlannerError, load_roadmap

path = Path(sys.argv[1])
try:
    tasks = load_roadmap(path)
except PlannerError as exc:
    print(f"error: invalid PASI roadmap: {exc}", file=sys.stderr)
    raise SystemExit(1)
print(f"Roadmap: {path} ({len(tasks)} tasks; dependency graph valid)")
PY

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

adopt_existing_runner=0
existing_runner_pid=""

if [[ -f "$RUNNER_PID_FILE" ]]; then
    pid="$(cat "$RUNNER_PID_FILE" 2>/dev/null || true)"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
        runner_command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
        if [[ "$runner_command_line" != *"pasi_extended_runtime_entrypoint.py"* ]]; then
            rm -f "$RUNNER_PID_FILE"
            printf 'PASI overnight runner PID %s is live but is not the expected extended runtime; removed stale managed PID file.\n' "$pid" >&2
        elif [[ -f "$SUPERVISOR_PID_FILE" ]]; then
            supervisor_pid="$(cat "$SUPERVISOR_PID_FILE" 2>/dev/null || true)"
            if [[ "$supervisor_pid" =~ ^[0-9]+$ ]] && kill -0 "$supervisor_pid" 2>/dev/null; then
                printf 'PASI overnight runner and supervisor are already active (runner PID %s, supervisor PID %s).\n' "$pid" "$supervisor_pid"
                exit 0
            fi
            printf 'PASI overnight engine PID %s is live without its supervisor; launching a supervisor to adopt the existing engine.\n' "$pid"
            adopt_existing_runner=1
            existing_runner_pid="$pid"
        else
            printf 'PASI overnight engine PID %s is live without its supervisor; launching a supervisor to adopt the existing engine.\n' "$pid"
            adopt_existing_runner=1
            existing_runner_pid="$pid"
        fi
    else
        rm -f "$RUNNER_PID_FILE"
    fi
fi

# Each run is isolated, but the consolidated branch may already be attached
# to a dedicated worktree left by an earlier run. Reuse that exact worktree
# when it is registered to the requested branch; never force-reset or delete
# an existing worktree from this launcher.
requested_branch="${PASI_OVERNIGHT_BRANCH:-}"
configured_worktree="${PASI_OVERNIGHT_WORKTREE:-}"

if (( adopt_existing_runner == 1 )); then
    if [[ ! -f "$STATE_FILE" ]]; then
        printf 'error: live PASI runner PID %s has no state file to recover its branch/worktree identity; refusing to risk a duplicate engine.\n' "$existing_runner_pid" >&2
        exit 3
    fi
    state_values="$("$PYTHON" - "$STATE_FILE" <<'PY'
import json
import sys
from pathlib import Path

try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(1)
branch = payload.get("branch")
worktree = payload.get("worktree")
if not isinstance(branch, str) or not branch.strip() or not isinstance(worktree, str) or not worktree.strip():
    raise SystemExit(1)
print(branch.strip())
print(worktree.strip())
PY
)" || state_values=""
    state_branch="$(printf '%s\n' "$state_values" | sed -n '1p')"
    state_worktree="$(printf '%s\n' "$state_values" | sed -n '2p')"
    if [[ -z "$state_branch" || -z "$state_worktree" ]]; then
        printf 'error: live PASI runner PID %s has invalid state identity; refusing to risk a duplicate engine.\n' "$existing_runner_pid" >&2
        exit 3
    fi
    if [[ -n "$requested_branch" && "$requested_branch" != "$state_branch" ]]; then
        printf 'error: live PASI runner PID %s is on branch %s, not requested branch %s.\n' "$existing_runner_pid" "$state_branch" "$requested_branch" >&2
        exit 3
    fi
    if [[ -n "$configured_worktree" && "$(realpath -m -- "$configured_worktree")" != "$(realpath -m -- "$state_worktree")" ]]; then
        printf 'error: live PASI runner PID %s is using worktree %s, not requested worktree %s.\n' "$existing_runner_pid" "$state_worktree" "$configured_worktree" >&2
        exit 3
    fi
    requested_branch="${requested_branch:-$state_branch}"
    configured_worktree="${configured_worktree:-$state_worktree}"
    printf 'Adopting existing PASI runner identity: branch=%s worktree=%s.\n' "$requested_branch" "$configured_worktree"
fi

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
    nohup bash -c 'exec 9>&-; exec "$@"' _ env PYTHONPATH="$PYTHONPATH" "$PYTHON" "$REPO_ROOT/scripts/pasi_log_router.py" --log "$log_file" --max-bytes 1048576 --backups 2 -- "$@" < /dev/null > /dev/null 2>&1 &
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

service_deadline=$((SECONDS + 20))
while (( SECONDS < service_deadline )); do
    bridge_ok=0
    curl -fsS --max-time 2 'http://127.0.0.1:8765/health' >/dev/null 2>&1 && bridge_ok=1 || true
    if (( bridge_ok == 1 )); then
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

browser_observation_ready() {
    "$PYTHON" - <<'PY'
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

root = Path.cwd()
controller_source_path = root / "automation" / "chromium" / "pasi-chatgpt" / "content.js"
try:
    controller_source = controller_source_path.read_text(encoding="utf-8")
    match = re.search(r"""\bconst\s+CONTROLLER_VERSION\s*=\s*['"]([^'"]+)['"]""", controller_source)
    expected_version = match.group(1).strip() if match else None
    token = (os.environ.get("PASI_BRIDGE_TOKEN", "") or (Path.home() / ".pasi" / "bridge-token").read_text(encoding="utf-8")).strip()
    request = urllib.request.Request("http://127.0.0.1:8765/browser/health", headers={"Authorization": f"Bearer {token}"}, method="GET")
    with urllib.request.urlopen(request, timeout=3.0) as response:
        payload = json.loads(response.read(2_000_000).decode("utf-8"))
except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError):
    raise SystemExit(1)

observation = payload.get("observation") if isinstance(payload, dict) else None
data = observation.get("data") if isinstance(observation, dict) and isinstance(observation.get("data"), dict) else observation
if not isinstance(data, dict):
    raise SystemExit(1)
if data.get("kind") != "chatgpt_health":
    raise SystemExit(1)
captured_at = data.get("captured_at")
if not isinstance(captured_at, str):
    raw_capture = observation.get("captured_at") if isinstance(observation, dict) else None
    captured_at = raw_capture if isinstance(raw_capture, str) else None
if not isinstance(captured_at, str):
    raise SystemExit(1)
try:
    captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - captured).total_seconds()
except ValueError:
    raise SystemExit(1)
if age_seconds < -5 or age_seconds > 30:
    raise SystemExit(1)
if data.get("native_controller") is not True:
    raise SystemExit(1)
if not isinstance(expected_version, str) or not expected_version.strip() or data.get("controller_version") != expected_version.strip():
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
# The 168-hour supervisor owns restart/recovery of the extended runtime. Its engine handoff target is scripts/pasi_extended_runtime_entrypoint.py.
nohup bash -c 'exec 9>&-; exec "$@"' _ env PYTHONPATH="$PYTHONPATH" "$PYTHON" "$REPO_ROOT/scripts/pasi_log_router.py" --log "$log_file" --max-bytes 2097152 --backups 4 -- bash "$REPO_ROOT/scripts/pasi_168h_supervisor.sh"     --hours 168     --worktree "$WORKTREE"     --branch "$BRANCH"     -- "${launcher_args[@]}" < /dev/null > /dev/null 2>&1 &
pid=$!

runner_start_deadline=$((SECONDS + ${PASI_STARTUP_VERIFY_SECONDS:-90}))
supervisor_ready=0
runner_ready=0
while (( SECONDS < runner_start_deadline )); do
    supervisor_pid=""
    runner_pid=""
    if [[ -f "$SUPERVISOR_PID_FILE" ]]; then
        supervisor_pid="$(cat "$SUPERVISOR_PID_FILE" 2>/dev/null || true)"
        if [[ "$supervisor_pid" =~ ^[0-9]+$ ]] && kill -0 "$supervisor_pid" 2>/dev/null; then
            supervisor_ready=1
        fi
    fi
    if [[ -f "$RUNNER_PID_FILE" ]]; then
        runner_pid="$(cat "$RUNNER_PID_FILE" 2>/dev/null || true)"
        if [[ "$runner_pid" =~ ^[0-9]+$ ]] && kill -0 "$runner_pid" 2>/dev/null; then
            runner_ready=1
        fi
    fi
    if (( supervisor_ready == 1 && runner_ready == 1 )); then
        break
    fi
    sleep 1
done

if (( supervisor_ready == 0 || runner_ready == 0 )); then
    if (( supervisor_ready == 1 )); then
        printf '%s\n' 'error: PASI supervisor started, but the extended engine did not publish a live runner PID within the startup verification window.' >&2
    fi
    printf '%s\n' 'error: detached PASI supervisor/runner did not become live within the startup verification window.' >&2
    printf 'Runner log: %s\n' "$log_file" >&2
    if [[ -s "$log_file" ]]; then
        tail -80 "$log_file" >&2 || true
    fi
    if [[ -n "$supervisor_pid" ]] && kill -0 "$supervisor_pid" 2>/dev/null; then
        kill -TERM "$supervisor_pid" 2>/dev/null || true
    fi
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
    fi
    exit 6
fi

printf 'Started PASI extended runner under 168-hour supervisor (launcher PID %s, supervisor PID %s, runner PID %s, 168 hours).\n' "$pid" "$supervisor_pid" "$runner_pid"

printf 'Worktree: %s\n' "$WORKTREE"
printf 'Branch: %s\n' "$BRANCH"
printf 'Log: %s\n' "$log_file"
printf 'State: %s\n' "$RUNTIME_DIR/state.json"
printf 'Action list: %s\n' "$REPO_ROOT/.runtime/automation/action-list.md"
printf 'Setup checklist: %s\n' "$REPO_ROOT/.runtime/automation/setup-requirements.md"