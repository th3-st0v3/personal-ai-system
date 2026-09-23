#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PASI_PYTHON:-$REPO_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" && -x "$HOME/.pasi/venv/bin/python" ]]; then
  PYTHON="$HOME/.pasi/venv/bin/python"
fi
[[ -x "$PYTHON" ]] || { echo "error: no usable PASI Python environment found" >&2; exit 1; }

STAMP="$(date -u +%Y%m%d-%H%M%S-%N)"
WORKTREE="$HOME/.pasi-worktrees/pasi-m0-acceptance-$STAMP"
BRANCH="pasi/m0-acceptance-$STAMP"
EVIDENCE_DIR="$REPO_ROOT/.runtime/acceptance"
LOG="$EVIDENCE_DIR/m0-live.log"
mkdir -p "$EVIDENCE_DIR"
export PYTHONPATH="$REPO_ROOT:${PYTHONPATH:-}"
export PASI_PRIMARY_CHATGPT_ONLY=1

# The native MV3 controller reads its private bridge credential from an
# unpacked extension resource. Keep that credential out of packaged archives,
# and never rotate the credential behind an already-healthy bridge without
# first confirming that the managed token exists.
TOKEN_FILE="$HOME/.pasi/bridge-token"
# The GitHub Actions checkout is not necessarily the directory from which the
# operator's authenticated unpacked Chromium extension is loaded. Prefer the
# canonical local workspace when it exists, while still staging the token into
# the acceptance checkout used by this job.
# The GitHub Actions checkout is not necessarily the directory from which the
# operator's authenticated unpacked Chromium extension is loaded. Prefer an
# explicit override, the canonical local workspace, and any other unpacked
# PASI extension roots discoverable on this runner.
BROWSER_EXTENSION_ROOT="${PASI_BROWSER_EXTENSION_ROOT:-$HOME/workspace/personal-ai-system/automation/chromium/pasi-chatgpt}"
BROWSER_EXTENSION_ROOT_FALLBACK="$REPO_ROOT/automation/chromium/pasi-chatgpt"
declare -a BROWSER_EXTENSION_ROOTS=()
add_browser_extension_root() {
  local candidate="$1"
  [[ -d "$candidate" ]] || return 0
  [[ -f "$candidate/manifest.json" && -f "$candidate/content.js" ]] || return 0
  local existing
  for existing in "${BROWSER_EXTENSION_ROOTS[@]}"; do
    [[ "$existing" == "$candidate" ]] && return 0
  done
  BROWSER_EXTENSION_ROOTS+=( "$candidate" )
}
add_browser_extension_root "$BROWSER_EXTENSION_ROOT"
add_browser_extension_root "$BROWSER_EXTENSION_ROOT_FALLBACK"
while IFS= read -r discovered_root; do
  add_browser_extension_root "$discovered_root"
done < <(find "$HOME" -type f -path "*/automation/chromium/pasi-chatgpt/manifest.json" -print 2>/dev/null | sed "s#/manifest.json##" | head -50)
if ((${#BROWSER_EXTENSION_ROOTS[@]} == 0)); then
  echo "error: no unpacked PASI ChatGPT extension root was found on the runner" >&2
  exit 10
fi
printf "M0 browser extension roots:\n" | tee -a "$LOG"
printf "  %s\n" "${BROWSER_EXTENSION_ROOTS[@]}" | tee -a "$LOG"
mkdir -p "$HOME/.pasi"


BRIDGE_URL="http://127.0.0.1:8765/health"
PREFLIGHT_FILE="$EVIDENCE_DIR/m0-preflight.txt"
BROWSER_HEALTH_URL="http://127.0.0.1:8765/browser/health"
BRIDGE_LOG="$EVIDENCE_DIR/m0-bridge.log"
BRIDGE_PID=""
BRIDGE_STARTED=0

cleanup() {
  if [[ -n "$WORKTREE" && -d "$WORKTREE" ]]; then
    git worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
  fi
  if (( BRIDGE_STARTED == 1 )) && [[ -n "$BRIDGE_PID" ]] && kill -0 "$BRIDGE_PID" 2>/dev/null; then
    kill "$BRIDGE_PID" 2>/dev/null || true
    wait "$BRIDGE_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

bridge_already_healthy=0
if curl -fsS --max-time 3 "$BRIDGE_URL" >/dev/null 2>&1; then
  bridge_already_healthy=1
fi

if (( bridge_already_healthy == 1 )); then
  if [[ ! -s "$TOKEN_FILE" ]]; then
    echo "error: PASI bridge is already healthy but its managed token file is missing; refusing to rotate credentials behind the live bridge" >&2
    exit 7
  fi
  if ! curl -fsS --max-time 3 -H "Authorization: Bearer $(cat "$TOKEN_FILE")" "$BROWSER_HEALTH_URL" >/dev/null 2>&1; then
    echo "error: managed PASI bridge token does not authenticate against the already-healthy bridge; refusing to overwrite the live credential state" >&2
    exit 7
  fi
elif [[ ! -s "$TOKEN_FILE" ]]; then
  "$PYTHON" - <<'PY' > "$TOKEN_FILE"
import secrets
print(secrets.token_urlsafe(48))
PY
  chmod 600 "$TOKEN_FILE"
fi

PASI_BRIDGE_TOKEN="$(cat "$TOKEN_FILE")"
[[ -n "$PASI_BRIDGE_TOKEN" ]] || { echo "error: PASI bridge token is empty" >&2; exit 7; }
export PASI_BRIDGE_TOKEN

provision_browser_extension_tokens() {
  local extension_dir
  for extension_dir in "${BROWSER_EXTENSION_ROOTS[@]}"; do
    install -m 600 "$TOKEN_FILE" "$extension_dir/.bridge-token"
    echo "M0 bridge token provisioned: $extension_dir/.bridge-token" | tee -a "$LOG"
  done
  if [[ -d "$REPO_ROOT/.runtime/chromium/pasi-chatgpt" ]]; then
    install -m 600 "$TOKEN_FILE" "$REPO_ROOT/.runtime/chromium/pasi-chatgpt/.bridge-token"
  fi
}

if (( bridge_already_healthy == 0 )); then
  provision_browser_extension_tokens
  "$PYTHON" -m automation.orchestrator.bridge >"$BRIDGE_LOG" 2>&1 &
  BRIDGE_PID="$!"
  BRIDGE_STARTED=1
  bridge_deadline=$((SECONDS + 20))
  while (( SECONDS < bridge_deadline )); do
    if curl -fsS --max-time 2 "$BRIDGE_URL" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
else
  provision_browser_extension_tokens
fi

if ! curl -fsS --max-time 2 "$BRIDGE_URL" >/dev/null 2>&1; then
  echo "error: PASI bridge did not become healthy on 127.0.0.1:8765" >&2
  echo "Bridge log: $BRIDGE_LOG" >&2
  [[ -s "$BRIDGE_LOG" ]] && tail -80 "$BRIDGE_LOG" >&2 || true
  exit 8
fi
if ! curl -fsS --max-time 3 -H "Authorization: Bearer $(cat "$TOKEN_FILE")" "$BROWSER_HEALTH_URL" >/dev/null 2>&1; then
  echo "error: PASI bridge token is not accepted by the browser-health endpoint" >&2
  exit 9
fi

# The real acceptance boundary requires the authenticated browser page itself.
# When the Windows Opera instance is already running, open ChatGPT through that
# existing profile so the native content script has a real tab to attach to.
if command -v powershell.exe >/dev/null 2>&1 && command -v tasklist.exe >/dev/null 2>&1; then
  if tasklist.exe 2>/dev/null | grep -qi '^opera\.exe'; then
    if powershell.exe -NoProfile -NonInteractive -Command "\$p = Get-CimInstance Win32_Process -Filter 'Name = \"opera.exe\"' | Where-Object { \$_.ExecutablePath } | Select-Object -First 1; if (\$p) { Start-Process -FilePath \$p.ExecutablePath -ArgumentList 'https://chatgpt.com/' | Out-Null; exit 0 }; exit 1" >/dev/null 2>&1; then
      echo "M0 browser bootstrap: opened https://chatgpt.com/ in the running Opera profile" | tee -a "$LOG"
    else
      echo "M0 browser bootstrap: could not open ChatGPT through the running Opera profile; continuing to the authenticated heartbeat gate" | tee -a "$LOG"
    fi
  fi
fi

TASK="M0 P0.1 live task acceptance: execute one real sustained PASI engineering task through the complete acceptance seam in this dedicated worktree. First inspect the existing M0 acceptance harness and the prior failure evidence. Then perform the smallest necessary related inspection or repair work needed to establish this exact chain: an authenticated ChatGPT response through the native PASI browser path, the normal PASI completion contract, extraction of the unified patch, successful git patch application, successful canonical validation via scripts/check_all.sh, and a new clean Git commit containing the required evidence artifact. Keep all of those steps inside this single task; do not turn them into separate tasks or stop after creating a proof file, making a tiny patch, or seeing one intermediate check pass. Only after the complete chain is directly evidenced, create acceptance/M0-LIVE-PROOF.txt containing exactly one line, PASI M0 LIVE PROOF, and return the normal PASI completion contract with the unified patch that produces it. Do not modify protected PASI runtime/control files. If the authenticated browser, contract, patch, canonical validation, or commit chain genuinely fails, report the concrete failure instead of claiming completion."

# M0 P0.1 is one live acceptance seam. The browser response, contract, patch,
# canonical gate, and commit are all part of the same bounded qualification task.
[[ -n "$WORKTREE" ]] || { echo "error: M0 acceptance worktree path is empty" >&2; exit 10; }
mkdir -p "$(dirname -- "$WORKTREE")"
echo "M0 acceptance worktree: $WORKTREE" | tee -a "$LOG"
git worktree add --quiet -b "$BRANCH" "$WORKTREE" HEAD

BEFORE_COMMIT="$("$PYTHON" -c 'import subprocess,sys; print(subprocess.check_output(["git","-C",sys.argv[1],"rev-parse","HEAD"], text=True).strip())' "$WORKTREE")"

if ! "$PYTHON" scripts/pasi_desktop_preflight.py --repo "$WORKTREE" --wait-seconds 45 --max-age-seconds 30 2>&1 | tee "$PREFLIGHT_FILE" | tee -a "$LOG"; then
  BROWSER_HEALTH_FAILURE="$EVIDENCE_DIR/m0-browser-health-failure.json"
  BROWSER_HOST_DIAGNOSTICS="$EVIDENCE_DIR/m0-browser-host-diagnostics.txt"
  curl -fsS --max-time 3 -H "Authorization: Bearer $(cat "$TOKEN_FILE")" "$BROWSER_HEALTH_URL" >"$BROWSER_HEALTH_FAILURE" 2>/dev/null || true
  {
    echo "=== Browser process diagnostics ==="
    if command -v tasklist.exe >/dev/null 2>&1; then
      tasklist.exe 2>/dev/null | grep -Ei 'opera|chrome|chromium' || true
    else
      echo "tasklist.exe unavailable"
    fi
    echo
    echo "=== PASI extension profile diagnostics ==="
    while IFS= read -r preferences; do
      [[ -f "$preferences" ]] || continue
      "$PYTHON" - "$preferences" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"{path}: unreadable ({exc.__class__.__name__})")
    raise SystemExit(0)

settings = payload.get("extensions", {}).get("settings", {})
if not isinstance(settings, dict):
    raise SystemExit(0)
for extension_id, entry in settings.items():
    if not isinstance(entry, dict):
        continue
    manifest = entry.get("manifest")
    if not isinstance(manifest, dict):
        continue
    name = str(manifest.get("name") or "")
    if "PASI ChatGPT Controller" not in name:
        continue
    print(json.dumps({
        "preferences": str(path),
        "extension_id": extension_id,
        "name": name,
        "manifest_version": manifest.get("version"),
        "path": entry.get("path"),
        "state": entry.get("state"),
        "location": entry.get("location")
    }, ensure_ascii=False))
PY
    done < <(find /mnt/c/Users -type f -path '*/Opera Software/Opera GX Stable/*/Preferences' -print 2>/dev/null | head -100)
  } >"$BROWSER_HOST_DIAGNOSTICS" 2>&1
  echo "M0 browser-health diagnostic: $BROWSER_HEALTH_FAILURE" | tee -a "$LOG"
  if [[ -s "$BROWSER_HEALTH_FAILURE" ]]; then cat "$BROWSER_HEALTH_FAILURE" | tee -a "$LOG"; fi
  echo "M0 browser-host diagnostic: $BROWSER_HOST_DIAGNOSTICS" | tee -a "$LOG"
  if [[ -s "$BROWSER_HOST_DIAGNOSTICS" ]]; then cat "$BROWSER_HOST_DIAGNOSTICS" | tee -a "$LOG"; fi
  exit 1
fi

RESPONSE_FILE="$EVIDENCE_DIR/m0-live-response.txt"
"$PYTHON" scripts/pasi_chat_guard.py "$TASK" --github public --timeout 3600 --repo "$WORKTREE" > >(tee "$RESPONSE_FILE" | tee -a "$LOG") 2>&1

"$PYTHON" - "$WORKTREE" "$BRANCH" "$BEFORE_COMMIT" "$TASK" "$RESPONSE_FILE" "$LOG" "$EVIDENCE_DIR" <<'PY'
import json
import re
import subprocess
import sys
from pathlib import Path
from scripts.pasi_overnight_engine_v2 import completion_contract, parse_response, verify_and_commit

worktree = Path(sys.argv[1])
branch = sys.argv[2]
before_commit = sys.argv[3]
task = sys.argv[4]
response_file = Path(sys.argv[5])
log = Path(sys.argv[6])
evidence_dir = Path(sys.argv[7])
response = response_file.read_text(encoding="utf-8")
status, summary, next_task, patch, allow_delete, values = parse_response(response)
if not completion_contract(status, values):
    raise SystemExit("M0 live acceptance returned a non-complete PASI response contract")
if not patch:
    raise SystemExit("M0 live acceptance returned an empty patch")

chat_url_match = re.search(r"^Chat URL:\s+(https://chatgpt\.com/c/[^\s]+)$", response, re.MULTILINE)
completion_match = re.search(r"^Completion:\s+(.+)$", response, re.MULTILINE)
if not chat_url_match:
    raise SystemExit("error: M0 response did not contain a verified ChatGPT conversation URL")
if not completion_match or completion_match.group(1).strip().casefold() != "complete":
    raise SystemExit("error: M0 response did not report terminal ChatGPT completion")

preflight_text = (evidence_dir / "m0-preflight.txt").read_text(encoding="utf-8")
if "PASI desktop preflight: PASS" not in preflight_text:
    raise SystemExit("error: M0 desktop preflight evidence is missing PASS")

proof_path = worktree / "acceptance" / "M0-LIVE-PROOF.txt"
commit, gate_output = verify_and_commit(
    worktree,
    branch,
    task,
    patch,
    allow_delete,
    push=False,
    promote=False,
)
if "ALL LOCAL VALIDATION PASSED" not in gate_output:
    raise SystemExit("error: canonical validation did not report ALL LOCAL VALIDATION PASSED")
if not proof_path.is_file():
    raise SystemExit("error: proof file missing")
if proof_path.read_text(encoding="utf-8") != "PASI M0 LIVE PROOF\n":
    raise SystemExit("error: proof file must contain exactly one line")

commit_parents = subprocess.run(
    ["git", "rev-list", "--parents", "-n", "1", commit],
    cwd=worktree,
    capture_output=True,
    text=True,
    check=False,
)
parent_fields = commit_parents.stdout.strip().split()
if commit_parents.returncode != 0 or len(parent_fields) != 2 or parent_fields[1] != before_commit:
    raise SystemExit(f"error: M0 commit {commit} is not the direct result of applying the acceptance patch")

committed_proof = subprocess.run(
    ["git", "show", f"{commit}:acceptance/M0-LIVE-PROOF.txt"],
    cwd=worktree,
    capture_output=True,
    text=True,
    check=False,
)
if committed_proof.returncode != 0 or committed_proof.stdout != "PASI M0 LIVE PROOF\n":
    raise SystemExit("error: required proof artifact is not present exactly in the committed tree")

commit_files = subprocess.run(
    ["git", "diff-tree", "--no-commit-id", "--name-status", "-r", commit],
    cwd=worktree,
    capture_output=True,
    text=True,
    check=False,
)
if commit_files.returncode != 0:
    raise SystemExit(f"error: could not inspect M0 commit contents: {commit_files.stderr}")
proof_status = [
    line.split("\t", 1)
    for line in commit_files.stdout.splitlines()
    if line.endswith("\tacceptance/M0-LIVE-PROOF.txt")
]
if proof_status != [["A", "acceptance/M0-LIVE-PROOF.txt"]]:
    raise SystemExit("error: M0 proof artifact was not newly added by the acceptance commit")

status_output = subprocess.run(
    ["git", "status", "--porcelain", "--untracked-files=all"],
    cwd=worktree,
    capture_output=True,
    text=True,
    check=False,
)
if status_output.returncode != 0 or status_output.stdout.strip():
    raise SystemExit(f"error: M0 worktree is not clean after commit: {status_output.stdout}")
runtime_check = subprocess.run(
    ["git", "status", "--porcelain", "--untracked-files=all", "--", ".runtime"],
    cwd=worktree,
    capture_output=True,
    text=True,
    check=False,
)
if runtime_check.returncode != 0 or runtime_check.stdout.strip():
    raise SystemExit(f"error: protected PASI runtime files changed: {runtime_check.stdout}")

evidence = evidence_dir / "m0-live.json"
evidence.write_text(
    json.dumps(
        {
            "gate": "M0",
            "status": "PASS",
            "provider": "chatgpt_browser",
            "authenticated_live_dom_required": True,
            "authenticated_browser_chat_url": chat_url_match.group(1),
            "completion": completion_match.group(1).strip(),
            "preflight_evidence": str((evidence_dir / "m0-preflight.txt").resolve()),
            "worktree": str(worktree.resolve()),
            "base_commit": before_commit,
            "branch": str(branch),
            "commit": commit,
            "proof_file": str(proof_path.resolve()),
            "log": str(log.resolve()),
            "canonical_validation": "ALL LOCAL VALIDATION PASSED",
            "gate_output": gate_output[-4000:],
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print("M0 PASS: authenticated ChatGPT response -> contract parsing -> git apply -> canonical validation -> committed proof -> clean worktree")
print(f"Evidence: {evidence}")
print(f"Commit: {commit}")
PY
