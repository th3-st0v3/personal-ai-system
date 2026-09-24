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
export PYTHONPATH="$REPO_ROOT:${PYTHONPATH:-}"

TOKEN_FILE="$HOME/.pasi/bridge-token"
[[ -s "$TOKEN_FILE" ]] || { echo "error: bridge token is missing: $TOKEN_FILE" >&2; exit 1; }
export PASI_BRIDGE_TOKEN="$(cat "$TOKEN_FILE")"

STAMP="$(date -u +%Y%m%d-%H%M%S-%N)"
PROMPT="M2 live recovery $STAMP: output the integers 1 through 1000, one integer per line, without commentary, then end with exactly M2-LIVE-$STAMP on its own line. PASI_M2_MANUAL_RELOAD_GATE: true"
OUT="$EVIDENCE_DIR/m2-live-$STAMP.json"

"$PYTHON" - "$PROMPT" "$OUT" "$STAMP" <<'PY'
import json, os, sys, time, urllib.parse, urllib.request
from pathlib import Path
prompt, out, stamp = sys.argv[1:]
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
idempotency_key = "m2-" + str(time.time_ns())
queued = request("POST", "/queue", {
    "operation_type": "prompt",
    "prompt": prompt,
    "idempotency_key": idempotency_key,
    "completion_markers": [f"M2-LIVE-{stamp}"],
})
operation = queued["operation"]
Path(out).write_text(json.dumps({
    "gate":"M2","status":"STARTED","operation_id":operation["operation_id"],
    "prompt":prompt,"idempotency_key":idempotency_key,"started_at":time.time(),
    "pre_restart_signature":before_sig,"pre_restart_chat_url":before_url,
    "stages": []
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

get_provisioning_observation() {
  "$PYTHON" <<'PY'
import json, os, urllib.request
req=urllib.request.Request(
    "http://127.0.0.1:8765/browser/provisioning",
    headers={"Authorization":"Bearer "+os.environ["PASI_BRIDGE_TOKEN"]},
    method="GET",
)
try:
    with urllib.request.urlopen(req, timeout=5) as response:
        observation=(json.loads(response.read(2000000).decode()).get("observation") or {})
except Exception:
    observation={}
data=observation.get("data") if isinstance(observation,dict) else None
if not isinstance(data,dict):
    data={}
print(json.dumps({
    "captured_at": observation.get("captured_at") if isinstance(observation,dict) else None,
    "kind": data.get("kind"),
    "action": data.get("action"),
    "existing_tab_count": data.get("existing_tab_count"),
    "after_create_tab_count": data.get("after_create_tab_count"),
    "requested_url": data.get("requested_url"),
    "created_tab_id": data.get("created_tab_id"),
    "selected_tab_id": data.get("selected_tab_id"),
    "selected_tab_url": data.get("selected_tab_url"),
    "selected_tab_active": data.get("selected_tab_active"),
    "injection_ready": data.get("injection_ready"),
    "existing_tab_ids": data.get("existing_tab_ids"),
    "existing_tab_urls": data.get("existing_tab_urls"),
    "after_create_tab_count": data.get("after_create_tab_count"),
    "after_create_tab_ids": data.get("after_create_tab_ids"),
    "after_create_tab_urls": data.get("after_create_tab_urls"),
}))
PY
}

wait_for_tab_provisioning() {
  local deadline=$((SECONDS + 120))
  while (( SECONDS < deadline )); do
    local result action count selected_tab_id accepted
    result="$(get_provisioning_observation 2>/dev/null || echo '{}')"
    action="$(printf '%s' "$result" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("action") or "")')"
    count="$(printf '%s' "$result" | "$PYTHON" -c 'import json,sys; d=json.load(sys.stdin); print(d.get("after_create_tab_count") or d.get("existing_tab_count") or 0)')"
    selected_tab_id="$(printf '%s' "$result" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("selected_tab_id") or "")')"
    accepted=1
    case "$action" in
      created)
        [[ "$count" == "1" ]] || accepted=0
        ;;
      existing_tabs_no_create|race_existing_tabs_no_create)
        [[ "$count" -ge 1 && -n "$selected_tab_id" ]] || accepted=0
        ;;
      *)
        accepted=0
        ;;
    esac
    if [[ "$accepted" == "1" ]]; then
      fresh="$("$PYTHON" - "$result" "$OUT" <<'PY'
import json, sys
from datetime import datetime
observation = json.loads(sys.argv[1])
started_at = float(json.load(open(sys.argv[2], encoding="utf-8")).get("started_at") or 0)
try:
    captured_epoch = datetime.fromisoformat(str(observation.get("captured_at")).replace("Z", "+00:00")).timestamp()
except Exception:
    captured_epoch = 0
print("1" if captured_epoch >= started_at else "0")
PY
)"
      if [[ "$fresh" == "1" ]]; then
        PROVISIONING_CREATED_JSON="$result"
        printf 'Native tab provisioning accepted (existing tab is valid): %s
' "$result"
        return 0
      fi
    fi
    sleep 2
  done
  echo "error: native tab provisioning did not produce a usable ChatGPT tab within 120 seconds" >&2
  echo "last provisioning observation: $(get_provisioning_observation 2>/dev/null || true)" >&2
  return 1
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

wait_for_exact_reclaim() {
  local deadline=$((SECONDS + 180))
  while (( SECONDS < deadline )); do
    local result
    result="$("$PYTHON" - "$operation_id" <<'PY'
import json, os, sys, urllib.parse, urllib.request
opid=sys.argv[1]
req=urllib.request.Request(
    "http://127.0.0.1:8765/operation?operation_id="+urllib.parse.quote(opid,safe=""),
    headers={"Authorization":"Bearer "+os.environ["PASI_BRIDGE_TOKEN"]},
    method="GET",
)
with urllib.request.urlopen(req, timeout=5) as response:
    op=(json.loads(response.read(2000000).decode()).get("operation") or {})
print(json.dumps({
    "status": op.get("status"),
    "retry_count": int(op.get("retry_count", 0) or 0),
    "controller_retry_count": int((op.get("retry_counts") or {}).get("controller", 0) or 0),
}))
PY
)"
    local retry_count controller_retry_count status
    retry_count="$(printf '%s' "$result" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["retry_count"])')"
    controller_retry_count="$(printf '%s' "$result" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["controller_retry_count"])')"
    status="$(printf '%s' "$result" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["status"] or "")')"
    if (( retry_count == 1 && controller_retry_count == 1 )); then
      case "$status" in
        queued|claimed|generating) return 0 ;;
      esac
    fi
    if (( retry_count > 1 || controller_retry_count > 1 )); then
      echo "error: M2 operation was reclaimed more than once: $result" >&2
      return 1
    fi
    sleep 2
  done
  echo "error: M2 browser reload did not produce exactly one retry/reclaim within 180 seconds" >&2
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
p["latest_provisioning"]=get("/browser/provisioning").get("observation")
op = p["latest_operation"] or {}
p.setdefault("stages", []).append({
    "stage": p.pop("_pending_stage", "snapshot"),
    "operation_status": op.get("status"),
    "retry_count": op.get("retry_count"),
    "retry_counts": op.get("retry_counts"),
    "recovery_events": op.get("recovery_events") or [],
    "checked_at": time.time(),
})
p["checked_at"]=time.time()
open(path,"w",encoding="utf-8").write(json.dumps(p,indent=2,ensure_ascii=False)+"\n")
PY
}

echo "Waiting for a usable PASI ChatGPT tab: existing tab accepted; zero-tab path must create exactly one..."
PROVISIONING_CREATED_JSON=""
wait_for_tab_provisioning || exit 2
export PROVISIONING_CREATED_JSON
"$PYTHON" - "$OUT" <<'PY'
import json, os, sys
path=sys.argv[1]
raw=os.environ.get("PROVISIONING_CREATED_JSON", "")
try:
    provisioning=json.loads(raw)
except json.JSONDecodeError as exc:
    raise SystemExit(f"invalid provisioning evidence: {exc}")
p=json.load(open(path,encoding="utf-8"))
p["tab_provisioning_initial"]=provisioning
p["tab_provisioning_created"]=provisioning
open(path,"w",encoding="utf-8").write(json.dumps(p,indent=2,ensure_ascii=False)+"
")
PY

echo "Waiting for the exact M2 operation to be claimed/generating..."
wait_for_active || { echo "error: M2 operation was not claimed within 180 seconds after tab provisioning" >&2; exit 2; }


wait_for_manual_reload_gate() {
  "$PYTHON" - "$operation_id" <<'PY'
import json, os, sys, time, urllib.parse, urllib.request
opid = sys.argv[1]
headers = {"Authorization": "Bearer " + os.environ["PASI_BRIDGE_TOKEN"]}
deadline = time.time() + 180
while time.time() < deadline:
    req = urllib.request.Request(
        "http://127.0.0.1:8765/operation?operation_id=" + urllib.parse.quote(opid, safe=""),
        headers=headers,
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        op = (json.loads(response.read(2000000).decode()).get("operation") or {})
    if (
        op.get("manual_reload_gate") is True
        and op.get("manual_reload_gate_armed") is True
        and op.get("manual_reload_gate_released") is not True
    ):
        print(json.dumps(op))
        raise SystemExit(0)
    if op.get("status") in {"failed", "cancelled"}:
        print(json.dumps(op), file=sys.stderr)
        raise SystemExit(2)
    time.sleep(1)
raise SystemExit(3)
PY
}

echo "Waiting for the durable M2 manual reload gate to arm..."
wait_for_manual_reload_gate || { echo "error: M2 manual reload gate did not arm after the original send" >&2; exit 2; }
"$PYTHON" - "$OUT" <<'PY'
import json, sys
path=sys.argv[1]
p=json.load(open(path,encoding="utf-8"))
p["_pending_stage"]="initial_active"
open(path,"w",encoding="utf-8").write(json.dumps(p,indent=2,ensure_ascii=False)+"\n")
PY
update_evidence

echo
echo "MANUAL STEP: close OR reload the exact ChatGPT tab recorded in $OUT."
echo "Do not substitute another ChatGPT tab. Press Enter after that exact tab is closed/reloaded."
read -r

echo "Waiting for browser recovery to requeue and reclaim the exact operation once..."
wait_for_exact_reclaim
"$PYTHON" - "$OUT" <<'PY'
import json, sys
path=sys.argv[1]
p=json.load(open(path,encoding="utf-8"))
p["_pending_stage"]="browser_reload_reclaimed_once"
open(path,"w",encoding="utf-8").write(json.dumps(p,indent=2,ensure_ascii=False)+"\n")
PY
update_evidence

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

echo "Restarting the managed PASI bridge and verifying exact operation retention..."
BRIDGE_LOG="$RUNTIME_DIR/bridge.log"
nohup bash -c 'exec 9>&-; exec "$@"' _ env PYTHONPATH="$PYTHONPATH" "$PYTHON" "$REPO_ROOT/scripts/pasi_log_router.py" --log "$BRIDGE_LOG" --max-bytes 1048576 --backups 2 -- "$PYTHON" -m automation.orchestrator.bridge < /dev/null > /dev/null 2>&1 &
NEW_BRIDGE_PID=$!
printf '%s\n' "$NEW_BRIDGE_PID" > "$BRIDGE_PID_FILE"

bridge_deadline=$((SECONDS + 30))
bridge_recovered=0
while (( SECONDS < bridge_deadline )); do
  if kill -0 "$NEW_BRIDGE_PID" 2>/dev/null &&
     curl -fsS --max-time 2 -H "Authorization: Bearer $PASI_BRIDGE_TOKEN" http://127.0.0.1:8765/health >/dev/null 2>&1; then
    bridge_recovered=1
    break
  fi
  sleep 1
done
(( bridge_recovered == 1 )) || { echo "error: restarted bridge did not become healthy" >&2; exit 4; }

NEW_BRIDGE_PID="$NEW_BRIDGE_PID" "$PYTHON" - "$OUT" <<'PY'
import json, os, sys
path=sys.argv[1]
p=json.load(open(path,encoding="utf-8"))
p["bridge_restart_pid"]=int(os.environ.get("NEW_BRIDGE_PID", "0"))
p["bridge_restart_verified"]=True
open(path,"w",encoding="utf-8").write(json.dumps(p,indent=2,ensure_ascii=False)+"\n")
PY

"$PYTHON" - "$OUT" <<'PY'
import json, sys
path=sys.argv[1]
p=json.load(open(path,encoding="utf-8"))
p["_pending_stage"]="bridge_restart_recovered"
open(path,"w",encoding="utf-8").write(json.dumps(p,indent=2,ensure_ascii=False)+"\n")
PY
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
RUNNER_LOG="$RUNTIME_DIR/runner.log"
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

"$PYTHON" - "$OUT" <<'PY'
import json, sys
path=sys.argv[1]
p=json.load(open(path,encoding="utf-8"))
p["_pending_stage"]="runner_restart_resumed"
open(path,"w",encoding="utf-8").write(json.dumps(p,indent=2,ensure_ascii=False)+"\n")
PY
update_evidence

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

BRIDGE_KILLED_AT="$BRIDGE_KILLED_AT" RUNNER_KILLED_AT="$RUNNER_KILLED_AT" RESUME_LOG="$RESUME_LOG" RUNNER_LOG="$RUNNER_LOG" NEW_RUNNER_PID="$NEW_RUNNER_PID" "$PYTHON" - "$OUT" <<'PY'
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
provisioning=p.get("tab_provisioning_initial") or p.get("tab_provisioning_created") or {}
provisioning_data=provisioning.get("data") if isinstance(provisioning,dict) else {}
if not isinstance(provisioning_data,dict):
    raise SystemExit("M2 requires initial tab provisioning evidence")
if provisioning_data.get("action") not in {"created", "existing_tabs_no_create", "race_existing_tabs_no_create"}:
    raise SystemExit(f"unexpected initial provisioning action: {provisioning_data.get('action')!r}")
pre_url=str(p.get("pre_restart_chat_url") or "")
if provisioning_data.get("action") == "created":
    if int(provisioning_data.get("after_create_tab_count", 0) or 0) != 1:
        raise SystemExit("M2 provisioning evidence did not prove exactly one created ChatGPT tab")
    requested_url=str(provisioning_data.get("requested_url") or "")
    if pre_url and requested_url != pre_url:
        raise SystemExit("M2 created-tab provisioning URL did not match the persisted pre-restart conversation URL")
else:
    selected_tab_id=provisioning_data.get("selected_tab_id")
    selected_tab_url=str(provisioning_data.get("selected_tab_url") or "")
    if not selected_tab_id:
        raise SystemExit("M2 existing-tab provisioning did not record the selected ChatGPT tab")
    if pre_url and selected_tab_url != pre_url:
        raise SystemExit("M2 selected existing ChatGPT tab did not match the persisted pre-restart conversation URL")

if op.get("operation_id") != p["operation_id"]:
    raise SystemExit("final response belonged to a different operation")
if op.get("prompt") != p["prompt"] or op.get("idempotency_key") != p["idempotency_key"]:
    raise SystemExit("operation identity changed during recovery")
if int(op.get("retry_count", 0) or 0) != 1:
    raise SystemExit(f"expected exactly one recovery/reclaim, got retry_count={op.get('retry_count')!r}")
retry_counts = op.get("retry_counts") or {}
if int(retry_counts.get("controller", 0) or 0) != 1:
    raise SystemExit(f"expected exactly one controller recovery/reclaim, got {retry_counts!r}")
events = op.get("recovery_events") or []
if not any(event.get("phase") == "reloading" for event in events if isinstance(event, dict)):
    raise SystemExit("M2 evidence is missing the browser reloading recovery event")
if not any(event.get("phase") == "preserve_current_chat" for event in events if isinstance(event, dict)):
    raise SystemExit("M2 evidence is missing the exact-operation preserve_current_chat recovery event")

runner_log_path = Path(os.environ["RUNNER_LOG"])
try:
    runner_log = runner_log_path.read_text(encoding="utf-8")
except OSError as exc:
    raise SystemExit(f"M2 could not read runner log after restart: {exc}")
initial_submit_count = runner_log.count(f"Prompt operation: {opid}")
resume_count = runner_log.count(f"Resuming persisted ChatGPT operation: {opid}")
if initial_submit_count != 1:
    raise SystemExit(f"expected exactly one original prompt submission for {opid}, got {initial_submit_count}")
if resume_count < 1:
    raise SystemExit(f"runner restart did not resume persisted operation {opid}")
runner_resume_lines = [
    line for line in runner_log.splitlines()
    if f"Resuming persisted ChatGPT operation: {opid}" in line
][-4:]

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
    "runner_log":os.environ["RUNNER_LOG"],
    "runner_resume_verified":True,
    "runner_resume_evidence":runner_resume_lines,
    "initial_prompt_submission_count":initial_submit_count,
    "new_runner_pid":int(os.environ["NEW_RUNNER_PID"]),
    "bridge_restart_verified":True,
    "runner_restart_verified":True,
    "duplicate_user_message_delta":0
})
Path(path).write_text(json.dumps(p,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
print("M2 PASS: exact operation survived tab, bridge, and runner restart without duplicate prompt")
print("Evidence: "+path)
PY
