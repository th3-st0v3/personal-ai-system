#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f "$REPO_ROOT/.venv/bin/python" ]]; then
    printf 'error: expected Python virtual environment at %s/.venv\n' "$REPO_ROOT" >&2
    exit 1
fi

mkdir -p "$REPO_ROOT/.runtime/overnight"

if [[ -f "$REPO_ROOT/.runtime/overnight/runner.pid" ]]; then
    pid="$(cat "$REPO_ROOT/.runtime/overnight/runner.pid" 2>/dev/null || true)"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
        printf 'PASI overnight runner is already active (PID %s)\n' "$pid"
        exit 0
    fi
    rm -f "$REPO_ROOT/.runtime/overnight/runner.pid"
fi

hours="${PASI_OVERNIGHT_HOURS:-10}"
log_file="$REPO_ROOT/.runtime/overnight/runner.log"

nohup "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/scripts/pasi_overnight.py" --hours "$hours" "$@" >>"$log_file" 2>&1 < /dev/null &
pid=$!

printf '%s\n' "$pid" > "$REPO_ROOT/.runtime/overnight/runner.pid"
printf 'Started PASI overnight runner (PID %s, %s hours).\n' "$pid" "$hours"
printf 'Log: %s\n' "$log_file"
printf 'State: %s\n' "$REPO_ROOT/.runtime/overnight/state.json"
