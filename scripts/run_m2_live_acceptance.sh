#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="$REPO_ROOT/.venv/bin/python"
RUNTIME_DIR="${PASI_RUNTIME_DIR:-$HOME/.pasi/overnight}"
EVIDENCE_DIR="$REPO_ROOT/.runtime/acceptance"
BRIDGE_PID_FILE="$RUNTIME_DIR/bridge.pid"
RUNNER_PID_FILE="$RUNTIME_DIR/runner.pid"
mkdir -p "$EVIDENCE_DIR"
export PYTHONPATH="$REPO_ROOT:$PYTHONPATH"

TOKEN_FILE="$HOME/.pasi/bridge-token"
[[ -s "$TOKEN_FILE" ]] || { echo "error: bridge token is missing: $TOKEN_FILE" >&2; exit 1; }
export PASI_BRIDGE_TOKEN="$(cat "$TOKEN_FILE")"

STAMP="$(date -u +%Y%m%d-%H%M%S-%N)"
PROMPT="M2 live recovery $STAMP: reply exactly M2-LIVE-$STAMP"
OUT="$EVIDENCE_DIR/m2-live-$STAMP.json"

"$PYTHON" - "$PROMPT" "$OUT" <<'PY'
import json, os, sys, time, urllib.parse, urllib.request
from pathlib import Path
prompt, out = sys.argv[1:]
headers = {"Authorization": "Bearer " + os.environ["PASI_BRIDGE_TOKEN"], "Content-Type": "application/json"}
def request(method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request("http://127.0.0.1:8765" + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read(2000000).decode())
state = request("GET", "/browser/state").get("observation") or {}
data = state.get("data") if isinstance(state, dict) and isinstance(state.get("data"), dict) else state
before_sig = data.get("conversation_signature") if isinstance(data, dict) else None
before_url = data.get("chat_url") if isinstance(data, dict) else None
queued = request("POST", "/queue", {"operation_type":"prompt","prompt":prompt,"idempotency_key":"m2-"+str(time.time_ns())})
operation = queued["operation"]
Path(out).write_text(json.dumps({
    "gate":"M2","status":"STARTED","operation_id":operation["operation_id"],
    "prompt":prompt,"started_at":time.time(),
    "pre_restart_signature":before_sig,"pre_restart_chat_url":before_url
}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(operation["operation_id"])
PY

operation_id="$("$PYTHON" - "$OUT" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["operation_id"])
PY
)"

get_operation_status() {
  "$PYTHON" - "$operation_id" <<'PY'
import json, os, sys, urllib.parse, urllib.request
opid=sys.argv[1]
req=urllib.request.Request(
    "http://127.0.0.1:8765/operation?operation_id="+urllib.parse.quote(opid,safe=""),
    headers={"Authorization":"Bearer "+os.environ["PASI_BRIDGE_TOKEN"]},
    method="GET",
)
with urllib.request.urlopen(req, timeout=5) as response:
    print((json.loads(response.read(2000000).decode()).get("operation") or {}).get("status",""))
PY
}

wait_for_active() {
  local deadline=$((SECONDS + 180))
  while (( SECONDS < deadline )); do
    local status
    status="$(get_operation_status 2>/dev/null || true)"
    case "$status" in
      claimed|generating) return 0 ;;
    esac
    sleep 2
  done
  return 1
}

update_evidence() {
  "$PYTHON" - "$OUT" <<'PY'
import json, os, sys, time, urllib.parse, urllib.request
path=sys.argv[1]
p=json.load(open(path,encoding="utf-8"))
token=os.environ["PASI_BRIDGE_TOKEN"]
headers={"Authorization":"Bearer "+token}
opid=p["operation_id"]
def get(path):
    req=urllib.request.Request("http://127.0.0.1:8765"+path,headers=headers,method="GET")
    with urllib.request.urlopen(req,timeout=5) as response:
        return json.loads(response.read(2000000).decode())
p["latest_operation"]=get("/operation?operation_id="+urllib.parse.quote(opid,safe="")).get("operation")
p["latest_health"]=get("/browser/health").get("observation")
p["latest_state"]=get("/browser/state").get("observation")
p["checked_at"]=time.time()
open(path,"w",encoding="utf-8").write(json.dumps(p,indent=2,ensure_ascii=False)+"\n")
PY
}

echo "Waiting for the exact M2 operation to be claimed/generating..."
wait_for_active || { echo "error: M2 operation was not claimed within 180 seconds" >&2; exit 2; }
update_evidence

echo
echo "MANUAL STEP: close OR reload the exact ChatGPT tab recorded in $OUT."
echo "Do not substitute another ChatGPT tab. Press Enter after that exact tab is closed/reloaded."
read -r

if [[ ! -s "$BRIDGE_PID_FILE" ]]; then
  echo "error: managed bridge PID file is missing: $BRIDGE_PID_FILE" >&2
  exit 3
fi
BRIDGE_PID="$(cat "$BRIDGE_PID_FILE")"
[[ "$BRIDGE_PID" =~ ^[0-9]+$ ]] || { echo "error: invalid bridge PID" >&2; exit 3; }
kill -0 "$BRIDGE_PID" 2>/dev/null || { echo "error: managed bridge PID is not live" >&2; exit 3; }
BRIDGE_KILLED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
kill -TERM "$BRIDGE_PID" 2>/dev/null || true
for _ in {1..20}; do
  kill -0 "$BRIDGE_PID" 2>/dev/null || break
  sleep 1
done

echo "Waiting for the supervised bridge restart and exact operation retention..."
bridge_deadline=$((SECONDS + 120))
bridge_recovered=0
while (( SECONDS < bridge_deadline )); do
  if curl -fsS --max-time 2 -H "Authorization: Bearer $PASI_BRIDGE_TOKEN" http://127.0.0.1:8765/health >/dev/null 2>&1; then
    bridge_recovered=1
    break
  fi
  sleep 1
done
(( bridge_recovered == 1 )) || { echo "error: supervised bridge did not recover" >&2; exit 4; }

update_evidence

if [[ ! -s "$RUNNER_PID_FILE" ]]; then
  echo "error: managed runner PID file is missing: $RUNNER_PID_FILE" >&2
  exit 5
fi
RUNNER_PID="$(cat "$RUNNER_PID_FILE")"
[[ "$RUNNER_PID" =~ ^[0-9]+$ ]] || { echo "error: invalid runner PID" >&2; exit 5; }
kill -0 "$RUNNER_PID" 2>/dev/null || { echo "error: managed runner PID is not live" >&2; exit 5; }
RUNNER_KILLED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
kill -TERM "$RUNNER_PID" 2>/dev/null || true
for _ in {1..20}; do
  kill -0 "$RUNNER_PID" 2>/dev/null || break
  sleep 1
done

RESUME_LOG="$EVIDENCE_DIR/m2-resume-$STAMP.log"
echo "Resuming the 168-hour runner from persisted state..."
bash scripts/start_pasi_168h.sh --resume 2>&1 | tee "$RESUME_LOG"

NEW_RUNNER_PID=""
for _ in {1..30}; do
  candidate="$(cat "$RUNNER_PID_FILE" 2>/dev/null || true)"
  if [[ "$candidate" =~ ^[0-9]+$ ]] && kill -0 "$candidate" 2>/dev/null; then
    NEW_RUNNER_PID="$candidate"
    break
  fi
  sleep 1
done
[[ -n "$NEW_RUNNER_PID" ]] || { echo "error: resumed runner did not become live" >&2; exit 6; }

echo "Waiting for the original operation to complete after runner restart..."
deadline=$((SECONDS + 900))
terminal=""
while (( SECONDS < deadline )); do
  terminal="$(get_operation_status 2>/dev/null || true)"
  case "$terminal" in
    completed|failed|cancelled) break ;;
  esac
  sleep 5
done
[[ "$terminal" == "completed" ]] || { echo "error: original operation did not complete after restart: $terminal" >&2; exit 7; }

BRIDGE_KILLED_AT="$BRIDGE_KILLED_AT" RUNNER_KILLED_AT="$RUNNER_KILLED_AT" RESUME_LOG="$RESUME_LOG" NEW_RUNNER_PID="$NEW_RUNNER_PID" "$PYTHON" - "$OUT" <<'PY'
import json, os, re, sys, time, urllib.parse, urllib.request
from pathlib import Path
path=sys.argv[1]
p=json.load(open(path,encoding="utf-8"))
token=os.environ["PASI_BRIDGE_TOKEN"]
headers={"Authorization":"Bearer "+token}
opid=p["operation_id"]
def get(path):
    req=urllib.request.Request("http://127.0.0.1:8765"+path,headers=headers,method="GET")
    with urllib.request.urlopen(req,timeout=5) as response:
        return json.loads(response.read(2000000).decode())
op=get("/operation?operation_id="+urllib.parse.quote(opid,safe="")).get("operation") or {}
state=get("/browser/state").get("observation") or {}
data=state.get("data") if isinstance(state,dict) and isinstance(state.get("data"),dict) else state
marker=re.search(r"M2-LIVE-[0-9]{8}-[0-9]{6}-[0-9]+", p["prompt"]).group(0)
if marker not in str(op.get("response_text") or ""):
    raise SystemExit("final response did not contain the original M2 marker")
def sig(v):
    m=re.match(r"^(\d+):(\d+):", str(v or ""))
    return (int(m.group(1)),int(m.group(2))) if m else None
before=sig(p.get("pre_restart_signature"))
after=sig(data.get("conversation_signature") if isinstance(data,dict) else None)
if not before or not after:
    raise SystemExit("M2 requires both pre- and post-restart conversation signatures")
if after[0]-before[0] != 1 or after[1]-before[1] != 1:
    raise SystemExit("conversation signature delta was not exactly +1/+1")
before_url=str(p.get("pre_restart_chat_url") or "")
after_url=str(data.get("chat_url") or "")
if not before_url or not after_url:
    raise SystemExit("M2 requires both pre- and post-restart exact chat URLs")
if before_url != after_url:
    raise SystemExit("conversation identity changed during M2 recovery")
p.update({
    "status":"PASS",
    "latest_operation":op,
    "latest_state":state,
    "completed_at":time.time(),
    "bridge_killed_at":os.environ["BRIDGE_KILLED_AT"],
    "runner_killed_at":os.environ["RUNNER_KILLED_AT"],
    "resume_log":os.environ["RESUME_LOG"],
    "new_runner_pid":int(os.environ["NEW_RUNNER_PID"]),
    "bridge_restart_verified":True,
    "runner_restart_verified":True,
    "duplicate_user_message_delta":0
})
Path(path).write_text(json.dumps(p,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
print("M2 PASS: exact operation survived tab, bridge, and runner restart without duplicate prompt")
print("Evidence: "+path)
PY
