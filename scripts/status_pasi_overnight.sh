#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="$REPO_ROOT/.runtime/overnight"
PID_FILE="$RUNTIME_DIR/runner.pid"
STATE_FILE="$RUNTIME_DIR/state.json"

if [[ -f "$PID_FILE" ]]; then
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
        printf 'Runner: ACTIVE (PID %s)\n' "$pid"
    else
        printf 'Runner: INACTIVE (stale PID file)\n'
    fi
else
    printf 'Runner: INACTIVE\n'
fi

if [[ -f "$STATE_FILE" ]]; then
    printf '\nState:\n'
    if command -v jq >/dev/null 2>&1; then
        jq '{run_id, started_at, deadline_at, branch, current_task, task_number, completed_tasks, failed_tasks, current_attempt, last_result, next_task}' "$STATE_FILE"
    else
        cat "$STATE_FILE"
    fi
fi

printf '\nServices:\n'
curl -fsS http://127.0.0.1:8765/health 2>/dev/null || printf 'bridge: unavailable\n'
printf '\n'
curl -fsS http://127.0.0.1:8766/health 2>/dev/null || printf 'controller distribution: unavailable\n'
