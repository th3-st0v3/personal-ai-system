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
printf 'PASI overnight runner required forced termination after graceful shutdown timeout.\n'
