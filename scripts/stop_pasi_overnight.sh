#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PID_FILE="$REPO_ROOT/.runtime/overnight/runner.pid"

if [[ ! -f "$PID_FILE" ]]; then
    printf 'PASI overnight runner is not active.\n'
    exit 0
fi

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ ! "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$PID_FILE"
    printf 'Removed stale PASI overnight PID file.\n'
    exit 0
fi

kill -TERM "$pid"
printf 'Requested graceful stop for PASI overnight runner PID %s.\n' "$pid"
