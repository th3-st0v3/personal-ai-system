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
# but make the M0 live gate self-sufficient for the generated staging tree.
TOKEN_FILE="$HOME/.pasi/bridge-token"
mkdir -p "$HOME/.pasi"
if [[ ! -s "$TOKEN_FILE" ]]; then
  "$PYTHON" - <<'PY' > "$TOKEN_FILE"
import secrets
print(secrets.token_urlsafe(48))
PY
  chmod 600 "$TOKEN_FILE"
fi
PASI_BRIDGE_TOKEN="$(cat "$TOKEN_FILE")"
[[ -n "$PASI_BRIDGE_TOKEN" ]] || { echo "error: PASI bridge token is empty" >&2; exit 7; }
export PASI_BRIDGE_TOKEN
for extension_dir in \
    "$REPO_ROOT/automation/chromium/pasi-chatgpt" \
    "$REPO_ROOT/.runtime/chromium/pasi-chatgpt"
do
  if [[ -d "$extension_dir" ]]; then
    install -m 600 "$TOKEN_FILE" "$extension_dir/.bridge-token"
  fi
done

TASK="M0 live qualification: treat this as one sustained qualification task, not a one-file task. Work through the complete current M0 gate in this dedicated acceptance worktree: (1) re-establish CI evidence against the current head, (2) confirm canonical validation, (3) complete the real authenticated ChatGPT DOM acceptance through the native PASI browser path, (4) confirm 168-hour PASI startup readiness, and (5) preserve already-verified capabilities. Inspect the relevant repository and previous failure evidence first, then make the smallest necessary related implementation changes and verify them. You may perform multiple implementation, inspection, and repair steps inside this single M0 task; do not treat any of those steps as a new task. Do not stop after creating the proof file, producing a small patch, or getting one test to pass. Continue working until every M0 acceptance criterion has direct evidence. Only after the full M0 gate is actually satisfied, create acceptance/M0-LIVE-PROOF.txt containing exactly one line, PASI M0 LIVE PROOF, and return the normal PASI completion contract with one unified patch. Do not modify protected PASI runtime files. If a real external obstacle prevents completion, report blocked with the concrete evidence rather than claiming success."

# M0 is a single live acceptance seam. Use the guarded ChatGPT path directly
# instead of the multi-task overnight engine so a real authenticated DOM
# acceptance reaches a bounded terminal result for this one proof task.
git worktree add --quiet -b "$BRANCH" "$WORKTREE" HEAD

RESPONSE_FILE="$EVIDENCE_DIR/m0-live-response.txt"
"$PYTHON" scripts/pasi_chat_guard.py "$TASK" --github public --timeout 900 --repo "$WORKTREE" > >(tee "$RESPONSE_FILE" | tee -a "$LOG") 2>&1

"$PYTHON" - "$WORKTREE" "$BRANCH" "$TASK" "$RESPONSE_FILE" "$LOG" "$EVIDENCE_DIR" <<'PY'
import json
import subprocess
import sys
from pathlib import Path
from scripts.pasi_overnight_engine_v2 import completion_contract, parse_response, verify_and_commit

worktree = Path(sys.argv[1])
branch = sys.argv[2]
task = sys.argv[3]
response_file = Path(sys.argv[4])
log = Path(sys.argv[5])
evidence_dir = Path(sys.argv[6])
response = response_file.read_text(encoding="utf-8")
status, summary, next_task, patch, allow_delete, values = parse_response(response)
if not completion_contract(status, values):
    raise SystemExit("M0 live acceptance returned a non-complete PASI response contract")
if not patch:
    raise SystemExit("M0 live acceptance returned an empty patch")

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
if not proof_path.is_file():
    raise SystemExit("error: proof file missing")
if proof_path.read_text(encoding="utf-8") != "PASI M0 LIVE PROOF\n":
    raise SystemExit("error: proof file must contain exactly one line")
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
            "worktree": str(worktree.resolve()),
            "branch": str(branch),
            "commit": commit,
            "proof_file": str(proof_path.resolve()),
            "log": str(log.resolve()),
            "gate_output": gate_output[-4000:],
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print("M0 PASS: authenticated ChatGPT browser response -> guarded parser -> git apply -> canonical validation -> commit")
print(f"Evidence: {evidence}")
print(f"Commit: {commit}")
PY
