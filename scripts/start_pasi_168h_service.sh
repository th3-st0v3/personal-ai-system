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

if ! command -v systemd-run >/dev/null 2>&1 || ! command -v systemctl >/dev/null 2>&1; then
    printf 'error: systemd user services are required for a durable 168-hour launch from GitHub Actions.\n' >&2
    printf 'The Actions job cannot safely own a detached weeklong process; enable WSL systemd and retry.\n' >&2
    exit 4
fi

if ! systemctl --user show-environment >/dev/null 2>&1; then
    printf 'error: the current WSL user session does not expose a working systemd user manager.\n' >&2
    exit 4
fi

if systemctl --user is-active --quiet "$UNIT_NAME" 2>/dev/null; then
    printf 'PASI 168-hour systemd service is already active (%s).\n' "$UNIT_NAME"
    exit 0
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

systemd-run \
    --user \
    --collect \
    --unit="$UNIT_NAME" \
    --description="PASI 168-hour unattended automation" \
    --property=KillMode=control-group \
    --property=TimeoutStopSec=30s \
    --working-directory="$SERVICE_ROOT" \
    --setenv=PASI_OVERNIGHT_BRANCH="$REF" \
    --setenv=PASI_RUNTIME_DIR="$RUNTIME_DIR" \
    --setenv=PASI_LOCAL_GATE_MODE="${PASI_LOCAL_GATE_MODE:-fast}" \
    --setenv=PASI_VENV="${PASI_VENV:-$HOME/.pasi/venv}" \
    --setenv=PATH="$PATH" \
    "$SERVICE_ROOT/scripts/start_pasi_168h.sh" --foreground-supervisor

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
