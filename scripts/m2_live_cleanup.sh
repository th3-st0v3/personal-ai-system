#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="$REPO_ROOT/.venv/bin/python"
RUNTIME_DIR="$HOME/.pasi/overnight"
if [[ -n "${PASI_RUNTIME_DIR:-}" ]]; then
  RUNTIME_DIR="$PASI_RUNTIME_DIR"
fi
QUEUE_FILE="$REPO_ROOT/.ai/queue.json"
TOKEN_FILE="$HOME/.pasi/bridge-token"
BRIDGE="http://127.0.0.1:8765"
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
OPERATION_ID=""

usage() {
  cat <<'EOF'
Usage:
  scripts/m2_live_cleanup.sh
  scripts/m2_live_cleanup.sh --operation-id <operation_id>
EOF
}

[[ -x "$PYTHON" ]] || { echo "error: expected $PYTHON" >&2; exit 1; }
[[ -s "$TOKEN_FILE" ]] || { echo "error: bridge token is missing: $TOKEN_FILE" >&2; exit 1; }
[[ -n "$BRANCH" && "$BRANCH" != "HEAD" ]] || { echo "error: could not determine current branch" >&2; exit 1; }

TOKEN="$(cat "$TOKEN_FILE")"

while (($#)); do
  case "$1" in
    --operation-id)
      [[ $# -ge 2 ]] || { echo "error: --operation-id requires a value" >&2; exit 2; }
      OPERATION_ID="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

operation_status() {
  local opid="$1"
  curl -fsS --max-time 5     -H "Authorization: Bearer $TOKEN"     "$BRIDGE/operation?operation_id=$("$PYTHON" -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "$opid")" |
    "$PYTHON" -c 'import json,sys; print((json.load(sys.stdin).get("operation") or {}).get("status",""))'
}

fail_operation() {
  local opid="$1"
  local reason="$2"
  "$PYTHON" - "$opid" "$reason" <<'PY'
import json
import os
import sys
import urllib.request

opid = sys.argv[1]
reason = sys.argv[2]
token = os.environ["PASI_BRIDGE_TOKEN"]
payload = json.dumps({"operation_id": opid, "error": reason}).encode()
request = urllib.request.Request(
    "http://127.0.0.1:8765/chat/failed",
    data=payload,
    headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    },
    method="POST",
)
with urllib.request.urlopen(request, timeout=5):
    pass
PY
  printf '%s
' "Cleared stale M2 operation: $opid"
}

export PASI_BRIDGE_TOKEN="$TOKEN"

cleanup_m2_operations() {
  local ids_file="$RUNTIME_DIR/m2-cleanup-operation-ids.txt"
  rm -f "$ids_file"

  if [[ -n "$OPERATION_ID" ]]; then
    printf '%s
' "$OPERATION_ID" > "$ids_file"
  elif [[ -s "$QUEUE_FILE" ]]; then
    "$PYTHON" - "$QUEUE_FILE" > "$ids_file" <<'PY'
import json
import sys

try:
    queue = json.loads(open(sys.argv[1], encoding="utf-8").read())
except Exception:
    queue = []

terminal = {"completed", "failed", "cancelled"}
for item in queue if isinstance(queue, list) else []:
    if not isinstance(item, dict) or item.get("status") in terminal:
        continue
    prompt = item.get("prompt")
    operation_id = item.get("operation_id")
    if (
        isinstance(prompt, str)
        and "PASI_M2_MANUAL_RELOAD_GATE: true" in prompt
        and isinstance(operation_id, str)
    ):
        print(operation_id)
PY
  fi

  while IFS= read -r opid; do
    [[ -n "$opid" ]] || continue
    status="$(operation_status "$opid" 2>/dev/null || true)"
    case "$status" in
      queued|claimed|generating|running)
        fail_operation "$opid" "M2 cleanup: stale operation from an interrupted acceptance run"
        ;;
    esac
  done < "$ids_file"

  rm -f "$ids_file"
}

pid_matches() {
  local pid="$1"
  local expected="$2"
  local command_line
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  [[ "$command_line" == *"$expected"* ]]
}

cleanup_stale_pid_file() {
  local name="$1"
  local file="$2"
  local expected="$3"
  [[ -f "$file" ]] || return 0
  local pid
  pid="$(cat "$file" 2>/dev/null || true)"
  if ! pid_matches "$pid" "$expected"; then
    rm -f "$file"
    printf '%s
' "Removed stale $name PID file."
  fi
}

managed_pid() {
  local file="$1"
  local expected="$2"
  [[ -f "$file" ]] || return 0
  local pid
  pid="$(cat "$file" 2>/dev/null || true)"
  if pid_matches "$pid" "$expected"; then
    printf '%s
' "$pid"
  fi
}

kill_duplicate_processes() {
  local label="$1"
  local preserved_pid="$2"
  local pattern_one="$3"
  local pattern_two="$4"
  local pattern_three="$5"
  local line pid args match
  while IFS= read -r line; do
    pid="$(printf '%s
' "$line" | awk '{print $1}')"
    args="$(printf '%s
' "$line" | cut -d' ' -f2-)"
    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    [[ "$pid" != "$$" && "$pid" != "$PPID" && "$pid" != "$preserved_pid" ]] || continue
    match=1
    [[ "$args" == *"$pattern_one"* ]] || match=0
    [[ "$args" == *"$pattern_two"* ]] || match=0
    if [[ -n "$pattern_three" && "$args" != *"$pattern_three"* ]]; then
      match=0
    fi
    if (( match == 1 )); then
      kill -TERM "$pid" 2>/dev/null || true
      printf '%s
' "Stopped duplicate $label process: PID $pid"
    fi
  done < <(ps -eo pid=,args= 2>/dev/null || true)
}

kill_duplicate_m2_harnesses() {
  local line pid args
  while IFS= read -r line; do
    pid="$(printf '%s
' "$line" | awk '{print $1}')"
    args="$(printf '%s
' "$line" | cut -d' ' -f2-)"
    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    [[ "$pid" != "$$" && "$pid" != "$PPID" ]] || continue
    [[ "$args" == *"run_m2_live_acceptance.sh"* ]] || continue
    kill -TERM "$pid" 2>/dev/null || true
    printf '%s
' "Stopped stale M2 harness process: PID $pid"
  done < <(ps -eo pid=,args= 2>/dev/null || true)
}

echo "=== PASI M2 CLEANUP ==="
echo "Branch: $BRANCH"

mkdir -p "$RUNTIME_DIR"
cleanup_m2_operations
kill_duplicate_m2_harnesses

cleanup_stale_pid_file "runner" "$RUNTIME_DIR/runner.pid" "pasi_extended_runtime_entrypoint.py"
cleanup_stale_pid_file "supervisor" "$RUNTIME_DIR/supervisor.pid" "pasi_168h_supervisor.sh"
cleanup_stale_pid_file "startup launcher" "$RUNTIME_DIR/start.pid" "start_pasi_168h.sh"
cleanup_stale_pid_file "bridge" "$RUNTIME_DIR/bridge.pid" "pasi_log_router.py"

runner_pid="$(managed_pid "$RUNTIME_DIR/runner.pid" "pasi_extended_runtime_entrypoint.py" || true)"
supervisor_pid="$(managed_pid "$RUNTIME_DIR/supervisor.pid" "pasi_168h_supervisor.sh" || true)"
start_pid="$(managed_pid "$RUNTIME_DIR/start.pid" "start_pasi_168h.sh" || true)"

kill_duplicate_processes "same-branch PASI runner" "$runner_pid"   "pasi_extended_runtime_entrypoint.py" "--hours 168" "--worktree $REPO_ROOT"

kill_duplicate_processes "same-branch PASI supervisor" "$supervisor_pid"   "pasi_168h_supervisor.sh" "--worktree $REPO_ROOT" "--branch $BRANCH"

kill_duplicate_processes "same-branch PASI startup launcher" "$start_pid"   "start_pasi_168h.sh" "--worktree $REPO_ROOT" "--branch $BRANCH"

remaining_m2="$("$PYTHON" - "$QUEUE_FILE" <<'PY'
import json
import sys

try:
    queue = json.loads(open(sys.argv[1], encoding="utf-8").read())
except Exception:
    queue = []

terminal = {"completed", "failed", "cancelled"}
for item in queue if isinstance(queue, list) else []:
    if not isinstance(item, dict) or item.get("status") in terminal:
        continue
    prompt = item.get("prompt")
    if isinstance(prompt, str) and "PASI_M2_MANUAL_RELOAD_GATE: true" in prompt:
        print(item.get("operation_id", ""))
PY
)"

if [[ -n "$remaining_m2" ]]; then
  echo "error: nonterminal M2 operations remain after cleanup:" >&2
  printf '%s
' "$remaining_m2" >&2
  exit 3
fi

echo "M2 operations: clean"
echo "M2 harness duplicates: cleaned"
echo "Same-branch runtime duplicates: cleaned"
echo "Cleanup complete."
