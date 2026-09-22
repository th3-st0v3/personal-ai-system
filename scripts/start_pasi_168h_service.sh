#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

REF="${PASI_OVERNIGHT_BRANCH:-${1:-}}"
if [[ -z "$REF" ]]; then
    printf 'error: a PASI overnight branch/ref is required\n' >&2
    exit 2
fi

UNIT_NAME="${PASI_OVERNIGHT_SYSTEMD_UNIT:-pasi-overnight-168h.service}"
SERVICE_ROOT="${PASI_OVERNIGHT_SERVICE_ROOT:-$HOME/.pasi/overnight-service/personal-ai-system}"
RUNTIME_DIR="${PASI_RUNTIME_DIR:-$HOME/.pasi/overnight}"
START_LOCK_FILE="${PASI_OVERNIGHT_SERVICE_LOCK:-$HOME/.pasi/overnight-service/start.lock}"
REQUESTED_ROADMAP="${PASI_ROADMAP_PATH:-roadmaps/pasi-default.json}"
SERVICE_PATH="${PASI_SERVICE_PATH:-$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"
PLANNER_MODEL="${PASI_PLANNER_MODEL:-}"
PLANNER_AI_RANK="${PASI_PLANNER_AI_RANK:-}"
BROWSER_EXTENSION_DIR="${PASI_BROWSER_EXTENSION_DIR:-$REPO_ROOT/.runtime/chromium/pasi-chatgpt}"

if ! command -v python3 >/dev/null 2>&1; then
    printf 'error: python3 is required for durable-service identity verification.\n' >&2
    exit 4
fi

if ! command -v systemd-run >/dev/null 2>&1 || ! command -v systemctl >/dev/null 2>&1; then
    printf 'error: systemd user services are required for a durable 168-hour launch from GitHub Actions.\n' >&2
    printf 'The Actions job cannot safely own a detached weeklong process; enable WSL systemd and retry.\n' >&2
    exit 4
fi

if ! systemctl --user show-environment >/dev/null 2>&1; then
    printf 'error: the current WSL user session does not expose a working systemd user manager.\n' >&2
    exit 4
fi

if [[ ! -d "$BROWSER_EXTENSION_DIR" || ! -f "$BROWSER_EXTENSION_DIR/manifest.json" ]]; then
    printf 'error: native PASI extension staging directory is missing or incomplete: %s\n' "$BROWSER_EXTENSION_DIR" >&2
    printf 'Build it with: python scripts/build_chromium_extension.py\n' >&2
    exit 4
fi

mkdir -p "$(dirname -- "$START_LOCK_FILE")"
exec 9>"$START_LOCK_FILE"
if ! flock -n 9; then
    printf 'error: another PASI durable-service start is already in progress.\n' >&2
    exit 7
fi

service_processes_are_live() {
    local state_pid supervisor_pid
    state_pid="$(cat "$RUNTIME_DIR/runner.pid" 2>/dev/null || true)"
    supervisor_pid="$(cat "$RUNTIME_DIR/supervisor.pid" 2>/dev/null || true)"
    [[ "$state_pid" =~ ^[0-9]+$ ]] && kill -0 "$state_pid" 2>/dev/null || return 1
    [[ "$supervisor_pid" =~ ^[0-9]+$ ]] && kill -0 "$supervisor_pid" 2>/dev/null || return 1
}

service_identity_matches() {
    [[ -f "$RUNTIME_DIR/state.json" ]] || return 1
    python3 - "$RUNTIME_DIR/state.json" "$SERVICE_ROOT" "$REF" "$REQUESTED_ROADMAP" <<'PY'
import json
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
service_root = Path(sys.argv[2]).resolve()
expected_branch = sys.argv[3]
requested_roadmap = Path(sys.argv[4])
expected_roadmap = (service_root / requested_roadmap).resolve() if not requested_roadmap.is_absolute() else requested_roadmap.resolve()
try:
    state = json.loads(state_path.read_text(encoding="utf-8"))
except (OSError, ValueError, TypeError):
    raise SystemExit(1)
actual_branch = state.get("branch")
actual_roadmap = state.get("roadmap_path")
if not isinstance(actual_branch, str) or not isinstance(actual_roadmap, str):
    raise SystemExit(1)
raise SystemExit(0 if actual_branch == expected_branch and Path(actual_roadmap).resolve() == expected_roadmap else 1)
PY
}

if systemctl --user is-active --quiet "$UNIT_NAME" 2>/dev/null; then
    if service_identity_matches; then
        if service_processes_are_live; then
            printf 'PASI 168-hour systemd service is already active for branch=%s roadmap=%s.\n' "$REF" "$REQUESTED_ROADMAP"
            exit 0
        fi
        printf 'error: PASI 168-hour systemd service %s has matching state identity but no live supervisor/runner PIDs; refusing to treat stale state as healthy.\n' "$UNIT_NAME" >&2
        exit 9
    fi
    printf 'error: PASI 168-hour systemd service %s is already active for a different branch or roadmap; refusing to attach another run to the same runtime state.\n' "$UNIT_NAME" >&2
    exit 8
fi

REMOTE_URL="$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || true)"
if [[ -z "$REMOTE_URL" ]]; then
    printf 'error: could not determine the repository origin URL.\n' >&2
    exit 3
fi

mkdir -p "$(dirname -- "$SERVICE_ROOT")"

if [[ ! -d "$SERVICE_ROOT/.git" ]]; then
    printf 'PASI service checkout: creating %s\n' "$SERVICE_ROOT"
    if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
        repo_slug="$REMOTE_URL"
        case "$repo_slug" in
            https://github.com/*)
                repo_slug="${repo_slug#https://github.com/}"
                ;;
            git@github.com:*)
                repo_slug="${repo_slug#git@github.com:}"
                ;;
        esac
        repo_slug="${repo_slug%.git}"
        gh repo clone "$repo_slug" "$SERVICE_ROOT" >/dev/null
    else
        git clone --no-tags "$REMOTE_URL" "$SERVICE_ROOT" >/dev/null
    fi
fi

if [[ ! -d "$SERVICE_ROOT/.git" ]]; then
    printf 'error: persistent PASI service checkout is not a Git repository: %s\n' "$SERVICE_ROOT" >&2
    exit 3
fi

if [[ -n "$(git -C "$SERVICE_ROOT" status --porcelain --untracked-files=all 2>/dev/null || true)" ]]; then
    printf 'error: persistent PASI service checkout is dirty; refusing to overwrite local changes.\n' >&2
    printf 'Service checkout: %s\n' "$SERVICE_ROOT" >&2
    exit 3
fi

git -C "$SERVICE_ROOT" fetch --no-tags origin "$REF" >/dev/null

if git -C "$SERVICE_ROOT" show-ref --verify --quiet "refs/heads/$REF"; then
    if ! git -C "$SERVICE_ROOT" merge-base --is-ancestor "refs/heads/$REF" "refs/remotes/origin/$REF" 2>/dev/null; then
        if git -C "$SERVICE_ROOT" merge-base --is-ancestor "refs/remotes/origin/$REF" "refs/heads/$REF" 2>/dev/null; then
            printf 'error: persistent PASI service checkout is ahead of origin/%s; refusing to reset potentially unpushed work.\n' "$REF" >&2
        else
            printf 'error: persistent PASI service checkout branch %s has diverged from origin/%s.\n' "$REF" "$REF" >&2
        fi
        exit 3
    fi
    git -C "$SERVICE_ROOT" merge --ff-only "refs/remotes/origin/$REF" >/dev/null
else
    git -C "$SERVICE_ROOT" switch --create "$REF" --track "refs/remotes/origin/$REF" >/dev/null
fi

if [[ "$(git -C "$SERVICE_ROOT" branch --show-current 2>/dev/null || true)" != "$REF" ]]; then
    printf 'error: persistent PASI service checkout is not on requested ref %s.\n' "$REF" >&2
    exit 3
fi

# The service outlives the Actions job, so verify that the host credentials can
# still perform the Git push that PASI needs after the temporary Actions token expires.
if ! git -C "$SERVICE_ROOT" push --dry-run origin "HEAD:$REF" >/dev/null 2>&1; then
    printf 'error: persistent PASI service checkout cannot authenticate a Git push to origin/%s.\n' "$REF" >&2
    printf 'Configure durable host GitHub credentials (for example, gh auth login + gh auth setup-git) and retry.\n' >&2
    exit 5
fi

mkdir -p "$RUNTIME_DIR"

# Run the foreground supervisor under systemd, but return immediately so this
# launcher can verify that the unit actually became live. The systemd unit,
# not the Actions process, owns the 168-hour lifetime.
systemd-run \
    --user \
    --collect \
    --no-block \
    --unit="$UNIT_NAME" \
    --description="PASI 168-hour unattended automation" \
    --property=KillMode=control-group \
    --property=TimeoutStopSec=30s \
    --working-directory="$SERVICE_ROOT" \
    --setenv=PASI_OVERNIGHT_BRANCH="$REF" \
    --setenv=PASI_RUNTIME_DIR="$RUNTIME_DIR" \
    --setenv=PASI_LOCAL_GATE_MODE="${PASI_LOCAL_GATE_MODE:-fast}" \
    --setenv=PASI_ROADMAP_PATH="$REQUESTED_ROADMAP" \
    --setenv=PASI_VENV="${PASI_VENV:-$HOME/.pasi/venv}" \
    --setenv=PASI_PLANNER_MODEL="$PLANNER_MODEL" \
    --setenv=PASI_PLANNER_AI_RANK="$PLANNER_AI_RANK" \
    --setenv=PASI_BROWSER_EXTENSION_DIR="$BROWSER_EXTENSION_DIR" \
    --setenv=PATH="$SERVICE_PATH" \
    bash "$SERVICE_ROOT/scripts/start_pasi_168h.sh" --foreground-supervisor

printf 'Started durable PASI 168-hour systemd service: %s\n' "$UNIT_NAME"
printf 'Service checkout: %s\n' "$SERVICE_ROOT"
printf 'Runtime state: %s/state.json\n' "$RUNTIME_DIR"

startup_deadline=$((SECONDS + ${PASI_STARTUP_VERIFY_SECONDS:-90}))
while (( SECONDS < startup_deadline )); do
    state_pid="$(cat "$RUNTIME_DIR/runner.pid" 2>/dev/null || true)"
    supervisor_pid="$(cat "$RUNTIME_DIR/supervisor.pid" 2>/dev/null || true)"
    unit_state="$(systemctl --user is-active "$UNIT_NAME" 2>/dev/null || true)"
    if [[ "$unit_state" == "active" ]] &&
       [[ "$state_pid" =~ ^[0-9]+$ ]] && kill -0 "$state_pid" 2>/dev/null &&
       [[ "$supervisor_pid" =~ ^[0-9]+$ ]] && kill -0 "$supervisor_pid" 2>/dev/null; then
        printf 'PASI 168-hour service verified live (supervisor PID %s, runner PID %s).\n' "$supervisor_pid" "$state_pid"
        exit 0
    fi
    if [[ "$unit_state" == "failed" || "$unit_state" == "inactive" ]]; then
        printf 'error: PASI 168-hour systemd service failed before the runner became live.\n' >&2
        systemctl --user status "$UNIT_NAME" --no-pager >&2 || true
        journalctl --user -u "$UNIT_NAME" -n 80 --no-pager >&2 || true
        exit 6
    fi
    sleep 1
done

printf 'error: PASI 168-hour systemd service did not publish live supervisor/runner PIDs within the startup verification window.\n' >&2
systemctl --user status "$UNIT_NAME" --no-pager >&2 || true
journalctl --user -u "$UNIT_NAME" -n 80 --no-pager >&2 || true
exit 6
