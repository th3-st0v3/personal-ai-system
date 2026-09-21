#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PID_FILE="$REPO_ROOT/.runtime/overnight/runner.pid"
START_PID_FILE="$REPO_ROOT/.runtime/overnight/start.pid"
BRIDGE_PID_FILE="$REPO_ROOT/.runtime/overnight/bridge.pid"

launcher_pid=""
if [[ -f "$START_PID_FILE" ]]; then
    candidate="$(cat "$START_PID_FILE" 2>/dev/null || true)"
    if [[ "$candidate" =~ ^[0-9]+$ ]] && kill -0 "$candidate" 2>/dev/null; then
        command_line="$(ps -p "$candidate" -o args= 2>/dev/null || true)"
        if [[ "$command_line" == *"start_pasi_overnight.sh"* || "$command_line" == *"start_pasi_168h.sh"* ]]; then
            launcher_pid="$candidate"
        else
            rm -f "$START_PID_FILE"
        fi
    else
        rm -f "$START_PID_FILE"
    fi
fi

if [[ -n "$launcher_pid" ]]; then
    kill -TERM "$launcher_pid" 2>/dev/null || true
    printf 'Requested graceful stop for PASI startup launcher PID %s.\n' "$launcher_pid"
    for _ in {1..10}; do
        if ! kill -0 "$launcher_pid" 2>/dev/null; then
            rm -f "$START_PID_FILE"
            printf 'PASI startup launcher stopped cleanly.\n'
            launcher_pid=""
            break
        fi
        sleep 1
    done
    if [[ -n "$launcher_pid" ]]; then
        kill -KILL "$launcher_pid" 2>/dev/null || true
        rm -f "$START_PID_FILE"
        printf 'PASI startup launcher required forced termination.\n'
    fi
fi

stop_managed_service() {
    local name="$1"
    local pid_file="$2"
    local expected="$3"

    [[ -f "$pid_file" ]] || return 0

    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ ! "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null; then
        rm -f "$pid_file"
        printf '%s: removed stale managed PID file.\n' "$name"
        return 0
    fi

    local command_line
    command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
    if [[ "$command_line" != *"$expected"* ]]; then
        rm -f "$pid_file"
        printf '%s: managed PID no longer matches expected service; left process untouched.\n' "$name"
        return 0
    fi

    local child
    while read -r child; do
        [[ -n "$child" ]] || continue
        kill -TERM "$child" 2>/dev/null || true
    done < <(pgrep -P "$pid" 2>/dev/null || true)
    kill -TERM "$pid" 2>/dev/null || true
    printf '%s: requested graceful stop for managed service PID %s.\n' "$name" "$pid"

    for _ in {1..10}; do
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$pid_file"
            printf '%s: stopped cleanly.\n' "$name"
            return 0
        fi
        sleep 1
    done

    while read -r child; do
        [[ -n "$child" ]] || continue
        kill -KILL "$child" 2>/dev/null || true
    done < <(pgrep -P "$pid" 2>/dev/null || true)
    kill -KILL "$pid" 2>/dev/null || true
    rm -f "$pid_file"
    printf '%s: required forced termination.\n' "$name"
}

if [[ ! -f "$PID_FILE" ]]; then
    if [[ -z "$launcher_pid" ]]; then
        printf 'PASI overnight runner is not active.\n'
    fi
    stop_managed_service "PASI bridge" "$BRIDGE_PID_FILE" "pasi_log_router.py"
    exit 0
fi

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ ! "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$PID_FILE"
    printf 'Removed stale PASI overnight PID file.\n'
    stop_managed_service "PASI bridge" "$BRIDGE_PID_FILE" "pasi_log_router.py"
    stop_managed_service "PASI controller distribution" "$CONTROLLER_PID_FILE" "pasi_controller_server.py"
    exit 0
fi

# The runner may be blocked in a synchronous child process (for example while
# waiting on a provider invocation). Stop the runner's descendant tree first so
# the supervisor can observe SIGTERM and exit cleanly. Do not signal ancestors.
children=()
queue=("$pid")
while ((${#queue[@]})); do
    current="${queue[0]}"
    queue=("${queue[@]:1}")
    while read -r child; do
        [[ -n "$child" ]] || continue
        children+=("$child")
        queue+=("$child")
    done < <(pgrep -P "$current" 2>/dev/null || true)
done

for ((index=${#children[@]}-1; index>=0; index--)); do
    kill -TERM "${children[index]}" 2>/dev/null || true
done
kill -TERM "$pid" 2>/dev/null || true
printf 'Requested graceful stop for PASI overnight runner PID %s and %s descendant process(es).\n' "$pid" "${#children[@]}"

for _ in {1..10}; do
    if ! kill -0 "$pid" 2>/dev/null; then
        rm -f "$PID_FILE"
        printf 'PASI overnight runner stopped cleanly.\n'
        stop_managed_service "PASI bridge" "$BRIDGE_PID_FILE" "pasi_log_router.py"
        exit 0
    fi
    sleep 1
done

# If the supervisor is still alive after its children were terminated and a
# graceful signal was given, force only the runner tree down rather than
# leaving a stale active PID that prevents a safe resume.
for ((index=${#children[@]}-1; index>=0; index--)); do
    kill -KILL "${children[index]}" 2>/dev/null || true
done
kill -KILL "$pid" 2>/dev/null || true
rm -f "$PID_FILE"
stop_managed_service "PASI bridge" "$BRIDGE_PID_FILE" "pasi_log_router.py"
printf 'PASI overnight runner required forced termination after graceful shutdown timeout.\n'