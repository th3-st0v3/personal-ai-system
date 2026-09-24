#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="$REPO_ROOT/.venv/bin/python"
TOKEN_FILE="$HOME/.pasi/bridge-token"
BRIDGE="http://127.0.0.1:8765"

usage() {
  echo "Usage: scripts/release_m2_manual_reload_gate.sh <operation_id>" >&2
}

[[ -x "$PYTHON" ]] || { echo "error: expected $PYTHON" >&2; exit 1; }
[[ -s "$TOKEN_FILE" ]] || { echo "error: bridge token is missing: $TOKEN_FILE" >&2; exit 1; }
[[ $# -eq 1 ]] || { usage; exit 2; }

OPERATION_ID="$1"
TOKEN="$(cat "$TOKEN_FILE")"
export PASI_BRIDGE_TOKEN="$TOKEN"

"$PYTHON" - "$OPERATION_ID" <<'PY'
import json
import os
import sys
import urllib.parse
import urllib.request

opid = sys.argv[1]
token = os.environ["PASI_BRIDGE_TOKEN"]
request = urllib.request.Request(
    "http://127.0.0.1:8765/operation?operation_id=" + urllib.parse.quote(opid, safe=""),
    headers={"Authorization": "Bearer " + token},
    method="GET",
)
with urllib.request.urlopen(request, timeout=5) as response:
    operation = (json.loads(response.read().decode()).get("operation") or {})

if operation.get("status") in {"completed", "failed", "cancelled"}:
    raise SystemExit(f"operation is already terminal: {operation.get('status')}")

prompt = str(operation.get("prompt") or "")
if "PASI_M2_MANUAL_RELOAD_GATE: true" not in prompt:
    raise SystemExit("operation is not an M2 manual-reload operation")

if operation.get("manual_reload_gate") is not True or operation.get("manual_reload_gate_armed") is not True:
    raise SystemExit("M2 manual reload gate is not armed")

if operation.get("manual_reload_gate_released") is True:
    print("M2 manual reload gate is already released.")
    raise SystemExit(0)
PY

curl -fsS --max-time 5   -X POST   -H "Authorization: Bearer $TOKEN"   -H "Content-Type: application/json"   "$BRIDGE/chat/manual-reload-gate/release"   -d "$(printf '%s' "$OPERATION_ID" | "$PYTHON" -c 'import json,sys; print(json.dumps({"operation_id":sys.argv[1]}))')"   >/dev/null

echo "Released M2 manual reload gate for $OPERATION_ID."
echo "The M2 harness should continue without pressing Enter."
