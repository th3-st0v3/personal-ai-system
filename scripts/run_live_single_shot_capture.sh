#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="$REPO_ROOT/.venv/bin/python"
EVIDENCE_DIR="$REPO_ROOT/.runtime/acceptance"
TOKEN_FILE="$HOME/.pasi/bridge-token"
STAMP="$(date -u +%Y%m%d-%H%M%S-%N)"
MARKER="CAPTURE-LIVE-$STAMP"
PROMPT="PASI live capture $STAMP: reply with exactly $MARKER and no commentary."
OUT="$EVIDENCE_DIR/live-capture-$STAMP.json"
mkdir -p "$EVIDENCE_DIR"
[[ -s "$TOKEN_FILE" ]] || { echo "error: bridge token is missing: $TOKEN_FILE" >&2; exit 1; }
export PASI_BRIDGE_TOKEN="$(cat "$TOKEN_FILE")"
export PYTHONPATH="$REPO_ROOT:\${PYTHONPATH:-}"

echo "=== PASI LIVE SINGLE-SHOT CAPTURE ==="
echo "Marker: $MARKER"

"$PYTHON" - "$PROMPT" "$MARKER" "$OUT" <<'PY'
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from scripts.m2_completion_markers import marker_satisfied

prompt, marker, out = sys.argv[1:]
headers = {"Authorization": "Bearer " + os.environ["PASI_BRIDGE_TOKEN"], "Content-Type": "application/json"}
max_wait = float(os.environ.get("PASI_LIVE_CAPTURE_TIMEOUT_SECONDS", "600"))


def request(method: str, path: str, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8765" + path,
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read(2000000).decode())


browser_state = request("GET", "/browser/state").get("observation") or {}
data = browser_state.get("data") if isinstance(browser_state, dict) and isinstance(browser_state.get("data"), dict) else browser_state
before_sig = data.get("conversation_signature") if isinstance(data, dict) else None
before_url = data.get("chat_url") if isinstance(data, dict) else None
idempotency_key = "live-capture-" + str(time.time_ns())

queued = request("POST", "/queue", {
    "operation_type": "prompt",
    "prompt": prompt,
    "idempotency_key": idempotency_key,
    "completion_markers": [marker],
})
operation = queued["operation"]
started_at = time.time()
Path(out).write_text(json.dumps({
    "gate": "LIVE_CAPTURE",
    "status": "STARTED",
    "operation_id": operation["operation_id"],
    "prompt": prompt,
    "marker": marker,
    "idempotency_key": idempotency_key,
    "started_at": started_at,
    "pre_signature": before_sig,
    "pre_chat_url": before_url,
    "max_wait_seconds": max_wait,
}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

operation_id = operation["operation_id"]
deadline = started_at + max_wait
while time.time() < deadline:
    current = request("GET", "/operation?operation_id=" + urllib.parse.quote(operation_id, safe="")).get("operation") or {}
    status = str(current.get("status") or "")
    if status == "completed":
        break
    if status in {"failed", "cancelled"}:
        raise SystemExit(json.dumps({"operation": current}, indent=2, ensure_ascii=False))
    time.sleep(2)
else:
    raise SystemExit(f"LIVE CAPTURE timed out after {max_wait:.1f}s")

browser_state = request("GET", "/browser/state").get("observation") or {}
data = browser_state.get("data") if isinstance(browser_state, dict) and isinstance(browser_state.get("data"), dict) else browser_state
after_sig = data.get("conversation_signature") if isinstance(data, dict) else None
after_url = data.get("chat_url") if isinstance(data, dict) else None
telemetry = request("GET", "/browser/telemetry")
current = request("GET", "/operation?operation_id=" + urllib.parse.quote(operation_id, safe="")).get("operation") or {}
response_text = current.get("response_text") if isinstance(current.get("response_text"), str) else ""


def signature(value):
    match = re.match(r"^(\d+):(\d+):", str(value or ""))
    return (int(match.group(1)), int(match.group(2))) if match else None


before = signature(before_sig)
after = signature(after_sig)
if not before or not after or (after[0] - before[0], after[1] - before[1]) != (1, 1):
    raise SystemExit(f"conversation signature delta was not +1/+1: before={before_sig!r} after={after_sig!r}")
if before_url != after_url:
    raise SystemExit(f"conversation URL changed during single-shot capture: {before_url!r} -> {after_url!r}")
if int(current.get("retry_count", 0) or 0) != 0:
    raise SystemExit(f"single-shot capture unexpectedly retried operation: {current.get('retry_count')!r}")
if current.get("response_text_available") is not True or not response_text.strip():
    raise SystemExit("single-shot capture completed without durable response text")
if not marker_satisfied(response_text, [marker]):
    raise SystemExit("single-shot capture response is missing the configured marker")

timing = current.get("timing") or {}
required_timing = ["injected_at_ms", "generation_start_ms", "completed_at_ms"]
missing_timing = [key for key in required_timing if not isinstance(timing.get(key), (int, float))]
if missing_timing:
    raise SystemExit(f"single-shot capture is missing timing evidence: {missing_timing}")

payload = json.loads(Path(out).read_text(encoding="utf-8"))
payload.update({
    "status": "PASS",
    "completed_at": time.time(),
    "latest_operation": current,
    "post_signature": after_sig,
    "post_chat_url": after_url,
    "timing": timing,
    "browser_telemetry": telemetry,
    "response_text_chars": len(response_text),
    "response_marker_verified": True,
    "retry_count_verified": True,
    "conversation_delta_verified": True,
    "chat_url_verified": True,
})
Path(out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("LIVE CAPTURE PASS: one real prompt completed with durable response evidence and no retry")
print("Evidence: " + out)
print("Operation: " + operation_id)
print("Timing: " + json.dumps(timing, sort_keys=True))
PY
