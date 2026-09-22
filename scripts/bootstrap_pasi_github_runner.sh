#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${PASI_GITHUB_RUNNER_REPO_URL:-https://github.com/th3-st0v3/personal-ai-system}"
RUNNER_DIR="${PASI_GITHUB_RUNNER_DIR:-$HOME/.pasi/actions-runner}"
RUNNER_NAME="${PASI_GITHUB_RUNNER_NAME:-$(hostname)-pasi}"
RUNNER_LABELS="${PASI_GITHUB_RUNNER_LABELS:-pasi-wsl,pasi-desktop,pasi-capabilities-v1}"
WORK_DIR="${PASI_GITHUB_RUNNER_WORK_DIR:-_work}"
TOKEN="${PASI_GITHUB_RUNNER_TOKEN:-}"

log() { printf '[pasi-runner] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

command -v curl >/dev/null || die "curl is required"
command -v tar >/dev/null || die "tar is required"
command -v python3 >/dev/null || die "python3 is required"

mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

if [[ ! -x "$RUNNER_DIR/config.sh" || ! -x "$RUNNER_DIR/run.sh" ]]; then
    log "Installing the latest GitHub Actions runner package into $RUNNER_DIR"
    metadata="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest)"
    version="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["tag_name"].lstrip("v"))' <<<"$metadata")"
    [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "could not determine a safe runner release version"

    archive="actions-runner-linux-x64-${version}.tar.gz"
    curl -fsSL -o "$archive" "https://github.com/actions/runner/releases/download/v${version}/${archive}"
    tar -xzf "$archive"
    rm -f "$archive"
fi

if [[ -f "$RUNNER_DIR/.runner" ]]; then
    log "Runner is already configured locally: $RUNNER_NAME"
else
    [[ -n "$TOKEN" ]] || die "PASI_GITHUB_RUNNER_TOKEN is required to register a new runner. Generate a fresh repository runner token in GitHub Settings; it expires after one hour."
    log "Registering repository runner '$RUNNER_NAME' with labels: $RUNNER_LABELS"
    ./config.sh         --unattended         --url "$REPO_URL"         --token "$TOKEN"         --name "$RUNNER_NAME"         --labels "$RUNNER_LABELS"         --work "$WORK_DIR"         --replace
fi

if [[ -x "$RUNNER_DIR/svc.sh" ]] && command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
    if [[ -f "$RUNNER_DIR/.service" ]]; then
        log "Starting existing systemd runner service"
    else
        log "Installing the systemd runner service"
        sudo ./svc.sh install
    fi
    sudo ./svc.sh start
    sudo ./svc.sh status
    log "Runner service is managed by systemd."
    exit 0
fi

log "systemd is not currently available in this WSL instance."
log "Start the configured runner with: cd '$RUNNER_DIR' && ./run.sh"
log "For persistent startup, enable WSL systemd and rerun this script."
