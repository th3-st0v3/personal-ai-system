#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="${PASI_RUNTIME_DIR:-$HOME/.pasi/overnight}"
PID_FILE="$RUNTIME_DIR/runner.pid"
STATE_FILE="$RUNTIME_DIR/state.json"
EVENT_LOG="$RUNTIME_DIR/events.jsonl"
PYTHON="$REPO_ROOT/.venv/bin/python"

printf '=== PASI WEEKLY RUN CHECK ===\n'
printf 'Repo: %s\n' "$REPO_ROOT"
printf 'Checked: %s\n' "$(date -Is)"
printf '\n'

runner_active=0
if [[ -f "$PID_FILE" ]]; then
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
        runner_active=1
        printf 'Runner: ACTIVE (PID %s)\n' "$pid"
    else
        printf 'Runner: INACTIVE / stale PID file\n'
    fi
else
    printf 'Runner: INACTIVE\n'
fi

if [[ -f "$STATE_FILE" ]]; then
    printf '\n--- STATE ---\n'
    if command -v jq >/dev/null 2>&1; then
        jq '{phase, run_id, started_at, deadline_at, branch, current_task, task_number, completed_tasks, failed_tasks, current_attempt, provider_limit_pauses, stop_reason, last_result, next_task}' "$STATE_FILE"
    else
        cat "$STATE_FILE"
    fi
else
    printf 'State: missing\n'
fi

printf '\n--- SERVICES ---\n'
for endpoint in \
    'bridge|http://127.0.0.1:8765/health' \
    'browser-observation|http://127.0.0.1:8765/browser/observation'; do
    name="${endpoint%%|*}"
    url="${endpoint#*|}"
    if curl -fsS --max-time 5 "$url" >/tmp/pasi-weekly-check.$$ 2>/dev/null; then
        printf '%s: OK\n' "$name"
        cat /tmp/pasi-weekly-check.$$
        printf '\n'
    else
        printf '%s: UNAVAILABLE\n' "$name"
    fi
    rm -f /tmp/pasi-weekly-check.$$
done

printf '\n--- RUNTIME EFFICIENCY ---\n'
if [[ -f "$EVENT_LOG" ]]; then
    if [[ -x "$PYTHON" ]]; then
        "$PYTHON" "$REPO_ROOT/scripts/pasi_runtime_telemetry.py" "$EVENT_LOG" || printf 'Runtime telemetry analysis failed; raw event log remains available.\n'
    else
        printf 'PASI virtualenv unavailable for runtime efficiency analysis\n'
    fi
else
    printf 'Event log: missing\n'
fi

printf '\n--- EVENT FRESHNESS ---\n'
if [[ -f "$EVENT_LOG" ]]; then
    tail -n 5 "$EVENT_LOG"
    printf '\nLast event age (seconds): '
    if command -v jq >/dev/null 2>&1 && [[ -x "$PYTHON" ]]; then
        last_timestamp="$(tail -n 1 "$EVENT_LOG" | jq -r '.timestamp // empty' 2>/dev/null || true)"
        if [[ -n "$last_timestamp" ]]; then
            "$PYTHON" - "$last_timestamp" <<'PY'
import sys
from datetime import datetime, timezone
value = sys.argv[1]
when = datetime.fromisoformat(value.replace('Z', '+00:00'))
print(max(0, int((datetime.now(timezone.utc) - when).total_seconds())))
PY
        else
            printf 'unknown\n'
        fi
    else
        printf 'jq or PASI virtualenv unavailable for precise freshness\n'
    fi
else
    printf 'Event log: missing\n'
fi

printf '\n--- RECOVERY DECISION ---\n'
if (( runner_active == 1 )); then
    printf 'No restart needed: runner process is alive.\n'
elif [[ -f "$STATE_FILE" ]]; then
    printf 'Runner is not alive. Recovery path:\n'
    printf '  bash scripts/start_pasi_168h.sh --resume\n'
    printf 'This reuses the persisted state when its deadline is still active; otherwise the extended entrypoint starts a fresh 168-hour run.\n'
else
    printf 'No persisted run state. Start a new run with:\n'
    printf '  bash scripts/start_pasi_168h.sh\n'
fi

printf '\nManual monitoring:\n'
printf '  bash scripts/status_pasi_overnight.sh\n'
printf '  tail -f %s/runner.log\n' "$RUNTIME_DIR"
printf '\nStop safely with:\n'
printf '  bash scripts/stop_pasi_overnight.sh\n'
