#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="$REPO_ROOT/.venv/bin/python"
[[ -x "$PYTHON" ]] || { echo "error: $PYTHON is missing" >&2; exit 1; }

STAMP="$(date -u +%Y%m%d-%H%M%S-%N)"
WORKTREE="$HOME/.pasi-worktrees/pasi-m0-acceptance-$STAMP"
BRANCH="pasi/m0-acceptance-$STAMP"
EVIDENCE_DIR="$REPO_ROOT/.runtime/acceptance"
LOG="$EVIDENCE_DIR/m0-live.log"
mkdir -p "$EVIDENCE_DIR"
export PYTHONPATH="$REPO_ROOT:${PYTHONPATH:-}"
export PASI_PRIMARY_CHATGPT_ONLY=1

TASK="M0 live acceptance: in the dedicated PASI acceptance worktree, create acceptance/M0-LIVE-PROOF.txt containing exactly one line, PASI M0 LIVE PROOF. Do not modify protected PASI runtime files. Run canonical validation. Return the normal PASI completion contract and one unified patch."

"$PYTHON" scripts/pasi_overnight_engine_v2.py   --hours 8   --task "$TASK"   --worktree "$WORKTREE"   --branch "$BRANCH"   --no-push > >(tee -a "$LOG") 2>&1 &
PID=$!

cleanup() { kill "$PID" 2>/dev/null || true; }
trap cleanup EXIT

EVENTS="$WORKTREE/.runtime/overnight/events.jsonl"
while kill -0 "$PID" 2>/dev/null; do
  if [[ -f "$EVENTS" ]] && grep -q '"kind": "task_completed"' "$EVENTS"; then
    kill -TERM "$PID" 2>/dev/null || true
    wait "$PID" || true
    break
  fi
  if [[ -f "$EVENTS" ]] && grep -q '"kind": "task_failed"' "$EVENTS"; then
    echo "M0 task failed; inspect $LOG" >&2
    exit 2
  fi
  sleep 1
done

[[ -d "$WORKTREE/.git" ]] || { echo "error: acceptance worktree was not created" >&2; exit 3; }
if [[ -f "$EVENTS" ]] && grep -q '"kind": "fallback_provider_route"' "$EVENTS"; then
    echo "error: M0 was completed through a fallback provider; live M0 requires the primary ChatGPT browser path." >&2
    exit 6
fi
COMMIT="$(git -C "$WORKTREE" rev-parse HEAD)"
PROOF="$WORKTREE/acceptance/M0-LIVE-PROOF.txt"
[[ -f "$PROOF" ]] && [[ "$(cat "$PROOF")" == "PASI M0 LIVE PROOF" ]] || { echo "error: proof file missing" >&2; exit 4; }
[[ -z "$(git -C "$WORKTREE" status --porcelain)" ]] || { echo "error: M0 worktree is not clean" >&2; exit 5; }

EVIDENCE="$EVIDENCE_DIR/m0-live.json"
"$PYTHON" - "$WORKTREE" "$BRANCH" "$COMMIT" "$LOG" "$EVIDENCE" <<'PY'
import json
import sys
from pathlib import Path
worktree, branch, commit, log, evidence = sys.argv[1:]
Path(evidence).write_text(json.dumps({
    "gate": "M0",
    "status": "PASS",
    "worktree": str(Path(worktree).resolve()),
    "branch": branch,
    "commit": commit,
    "proof_file": str((Path(worktree) / "acceptance/M0-LIVE-PROOF.txt").resolve()),
    "log": str(Path(log).resolve()),
}, indent=2) + "\n", encoding="utf-8")
print("M0 PASS: ChatGPT response -> parser -> git apply -> validation -> commit")
print(f"Evidence: {evidence}")
PY
