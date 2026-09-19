#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="$REPO_ROOT/.venv/bin/python"
RUNTIME_DIR="$REPO_ROOT/.runtime/overnight"
EVIDENCE_DIR="$REPO_ROOT/.runtime/acceptance"
mkdir -p "$EVIDENCE_DIR"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:${PYTHONPATH}}"

TOKEN_FILE="$HOME/.pasi/bridge-token"
[[ -s "$TOKEN_FILE" ]] || { echo "error: $TOKEN_FILE is missing" >&2; exit 1; }
export PASI_BRIDGE_TOKEN="$(cat "$TOKEN_FILE")"

STAMP="$(date -u +%Y%m%d-%H%M%S-%N)"
PROMPT="M2 live recovery $STAMP: reply exactly M2-LIVE-$STAMP"
OUT="$EVIDENCE_DIR/m2-live-$STAMP.json"

"$PYTHON" - "$PROMPT" "$OUT" <<'PY'
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

prompt, out = sys.argv[1:]
headers = {
    "Authorization": f"Bearer {os.environ['PASI_BRIDGE_TOKEN']}",
    "Content-Type": "application/json",
}

def request(method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8765" + path,
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read(2_000_000).decode())

queue = request(
    "POST",
    "/queue",
    {
        "operation_type": "prompt",
        "prompt": prompt,
        "idempotency_key": "m2-" + str(time.time_ns()),
    },
)
operation_id = queue["operation"]["operation_id"]
Path(out).write_text(json.dumps({
    "gate": "M2",
    "status": "STARTED",
    "operation_id": operation_id,
    "prompt": prompt,
    "started_at": time.time(),
}, indent=2) + "\n", encoding="utf-8")
print(f"operation_id={operation_id}")
print(f"evidence={out}")
PY

echo "Recovery stages against the exact operation_id:"
echo "1. Close/reload the exact ChatGPT conversation tab carrying this operation."
echo "2. Kill the managed bridge PID from $RUNTIME_DIR/bridge.pid, wait for health recovery, and verify the same operation remains active/recoverable."
echo "3. Kill the managed runner PID from $RUNTIME_DIR/runner.pid, then run: bash scripts/start_pasi_168h.sh --resume"
echo "Append final operation JSON, before/after conversation signatures, exact conversation URL, and PID/restart timestamps to the evidence file."
