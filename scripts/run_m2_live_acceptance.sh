)"

cleanup_current_m2_operation() {
  local status
  [[ -n "$operation_id" ]] || return 0
  status="$(get_operation_status 2>/dev/null || true)"
  if [[ "$status" == "queued" || "$status" == "claimed" || "$status" == "generating" || "$status" == "running" ]]; then
    local gate_state
    gate_state="$("$PYTHON" - "$operation_id" <<'PY'
import json, os, sys, urllib.parse, urllib.request
opid=sys.argv[1]
req=urllib.request.Request(
    "http://127.0.0.1:8765/operation?operation_id="+urllib.parse.quote(opid,safe=""),
    headers={"Authorization":"Bearer "+os.environ["PASI_BRIDGE_TOKEN"]},
    method="GET",
)
with urllib.request.urlopen(req, timeout=5) as response:
    op=json.loads(response.read(2000000).decode()).get("operation") or {}
print("released" if op.get("manual_reload_gate_released") is True else "armed")
PY
)" || gate_state="unknown"
    if [[ "$gate_state" != "released" ]]; then
      curl -fsS --max-time 5         -X POST         -H "Authorization: Bearer $PASI_BRIDGE_TOKEN"         -H "Content-Type: application/json"         "$BRIDGE/chat/failed"         -d "$("$PYTHON" - "$operation_id" <<'PY'
import json, sys
print(json.dumps({
    "operation_id": sys.argv[1],
    "error": "M2 harness exited before completion; cleaning its owned operation",
}))
PY
)" >/dev/null 2>&1 || true
    fi
  fi
}
trap cleanup_current_m2_operation EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
get_operation_status() {
  "$PYTHON" - "$operation_id" <<'PY'