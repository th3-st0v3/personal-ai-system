#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="${PASI_RUNTIME_DIR:-$HOME/.pasi/overnight}"
PID_FILE="$RUNTIME_DIR/runner.pid"
START_PID_FILE="$RUNTIME_DIR/start.pid"
BRIDGE_PID_FILE="$RUNTIME_DIR/bridge.pid"
SUPERVISOR_PID_FILE="$RUNTIME_DIR/supervisor.pid"
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

if [[ -f "$SUPERVISOR_PID_FILE" ]]; then
    supervisor_pid="$(cat "$SUPERVISOR_PID_FILE" 2>/dev/null || true)"
    if [[ "$supervisor_pid" =~ ^[0-9]+$ ]] && kill -0 "$supervisor_pid" 2>/dev/null; then
        printf 'Supervisor: ACTIVE (PID %s)\n' "$supervisor_pid"
    else
        printf 'Supervisor: INACTIVE (stale PID file)\n'
    fi
else
    printf 'Supervisor: INACTIVE\n'
fi

if [[ -f "$START_PID_FILE" ]]; then
    start_pid="$(cat "$START_PID_FILE" 2>/dev/null || true)"
    if [[ "$start_pid" =~ ^[0-9]+$ ]] && kill -0 "$start_pid" 2>/dev/null; then
        command_line="$(ps -p "$start_pid" -o args= 2>/dev/null || true)"
        if [[ "$command_line" == *"start_pasi_overnight.sh"* || "$command_line" == *"start_pasi_168h.sh"* ]]; then
            printf 'Startup launcher: ACTIVE (PID %s)\n' "$start_pid"
        else
            printf 'Startup launcher: INACTIVE (stale PID file)\n'
        fi
    else
        printf 'Startup launcher: INACTIVE (stale PID file)\n'
    fi
else
    printf 'Startup launcher: INACTIVE\n'
fi

if [[ -f "$STATE_FILE" ]]; then
    printf '\nState:\n'
    if command -v jq >/dev/null 2>&1; then
        jq '{schema_version, phase, run_id, started_at, deadline_at, branch, current_task, task_number, completed_tasks, failed_tasks, current_attempt, task_retry_cycle, same_failure_cycles, automation_tasks_since_gate, automation_gates, provider_limit_pauses, stop_reason, last_result, next_task}' "$STATE_FILE"
    else
        cat "$STATE_FILE"
    fi
fi

printf '\nManaged services:\n'
for spec in \
    "PASI bridge|$BRIDGE_PID_FILE|pasi_log_router.py"; do
    name="$(printf '%s' "$spec" | cut -d'|' -f1)"
    pid_file="$(printf '%s' "$spec" | cut -d'|' -f2)"
    expected="$(printf '%s' "$spec" | cut -d'|' -f3)"
    if [[ -f "$pid_file" ]]; then
        pid="$(cat "$pid_file" 2>/dev/null || true)"
        if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
            command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
            if [[ "$command_line" == *"$expected"* ]]; then
                printf '%s: MANAGED (PID %s)\n' "$name" "$pid"
            else
                printf '%s: PID FILE MISMATCH\n' "$name"
            fi
        else
            printf '%s: STALE PID FILE\n' "$name"
        fi
    else
        printf '%s: not managed by this launcher\n' "$name"
    fi
done

printf '\nServices:\n'
curl -fsS --max-time 3 http://127.0.0.1:8765/health 2>/dev/null || printf 'bridge: unavailable\n'
printf '\n'
token=""
if [[ -n "${PASI_BRIDGE_TOKEN:-}" ]]; then
    token="$PASI_BRIDGE_TOKEN"
elif [[ -r "$HOME/.pasi/bridge-token" ]]; then
    token="$(cat "$HOME/.pasi/bridge-token" 2>/dev/null || true)"
fi
if [[ -n "$token" ]]; then
    curl -fsS --max-time 3 -H "Authorization: Bearer $token" http://127.0.0.1:8765/browser/health 2>/dev/null || printf 'browser health: unavailable\n'
else
    printf 'browser health: bridge token unavailable\n'
fi

printf '\nResource evidence:\n'
RESOURCE_SAMPLES_FILE="$RUNTIME_DIR/resource-samples.jsonl"
if [[ -f "$RESOURCE_SAMPLES_FILE" ]]; then
    printf 'samples: %s bytes\n' "$(wc -c < "$RESOURCE_SAMPLES_FILE")"
    printf 'last sample: '
    tail -n 1 "$RESOURCE_SAMPLES_FILE" 2>/dev/null || printf 'unavailable'
else
    printf 'resource samples: not present yet\n'
fi
