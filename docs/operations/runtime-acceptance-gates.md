# PASI M0/M1/M2 Runtime Acceptance Gates

This document defines the final live-runtime evidence procedure. CI establishes deterministic repository contracts; M0, M1, and M2 additionally require the authenticated local ChatGPT/Chromium session.

## Preconditions

Run from `~/workspace/personal-ai-system` with the PASI virtualenv active. Unattended validation also requires `bubblewrap` (`bwrap`) so repository checks cannot read host credentials or use the host network. The native Chromium controller must be enabled and the ChatGPT session must be authenticated.

```bash
cd ~/workspace/personal-ai-system
source .venv/bin/activate
curl -fsS http://127.0.0.1:8765/health
curl -fsS -H "Authorization: Bearer $(cat ~/.pasi/bridge-token)" http://127.0.0.1:8765/browser/health
```

The browser-health observation must identify the native controller and match the extension version in `automation/chromium/pasi-chatgpt/manifest.json`. For M2, a ChatGPT tab may already be open; the harness uses that existing tab rather than requiring a zero-tab starting state. The zero-tab path remains covered by requiring exactly one created ChatGPT tab.

## M0 — real task through response → parser → apply → validation → commit

Run:

```bash
bash scripts/run_m0_live_acceptance.sh
```

The harness creates a dedicated local worktree/branch, submits one real task through the PASI ChatGPT path, stops after the first completed task, verifies the proof file in the committed worktree, and verifies the worktree is clean.

Required evidence:

```
.runtime/acceptance/m0-live.json
.runtime/acceptance/m0-live.log
```

The evidence is valid only when the task completed through ChatGPT response extraction, completion-contract parsing, `git apply`, canonical validation, and a local commit. The acceptance branch must not be pushed.

## M1 — 20 consecutive prompts

Run:

```bash
python scripts/run_m1_live_acceptance.py
```

The harness creates a fresh ChatGPT conversation and sends exactly 20 uniquely marked prompts. For every prompt it verifies a terminal `complete` operation, checks the unique response marker, and compares the durable conversation signature before and after the prompt.

M1 passes only when all 20 operations complete, every response contains its unique marker, each operation changes the signature by exactly +1 user message and +1 assistant message, and zero terminal `CHAT_*` verdicts occur.

Evidence:

```
.runtime/acceptance/m1-live.json
```

Any non-1/+1 delta, missing response marker, non-complete operation, terminal `CHAT_*` error, or transport failure is a gate failure and must remain visible.

## M2 — kill/restart recovery

Run:

```bash
bash scripts/run_m2_live_acceptance.sh
```

Record the printed `operation_id`. Exercise recovery against that exact operation in this order:

1. Close or reload the exact ChatGPT conversation tab carrying the operation. Never substitute another ChatGPT tab.
2. Kill the managed bridge process identified by `.runtime/overnight/bridge.pid`, wait for bridge health to return, and verify the same operation ID remains active/recoverable.
3. Kill the managed runner process identified by `.runtime/overnight/runner.pid`, then resume it with `bash scripts/start_pasi_168h.sh --resume`.

The terminal evidence must show the original operation ID was reclaimed/requeued exactly once after the browser reload (retry_count == 1 and controller retry count == 1), while the bridge and runner restarts preserve that same operation. The runner log must contain exactly one original `Prompt operation: <operation_id>` submission and at least one `Resuming persisted ChatGPT operation: <operation_id>` line after the runner restart, proving the resumed runner reused the persisted operation instead of submitting the prompt again. The existing bridge unit tests separately prove queue idempotency across a bridge restart; the live gate avoids replaying the queue request because a very fast completion could make a terminal idempotency-key replay create a new operation. The original ChatGPT prompt must still produce exactly one user-message increment and one assistant-message increment, with the final response bound to the same operation and conversation URL.

The generated M2 artifact is `.runtime/acceptance/m2-live-*.json`. It records stage snapshots for browser reload, bridge restart, and runner restart, the final operation/recovery events, runner-resume evidence from `runner.log`, before/after conversation signatures, the exact conversation URL, and bridge/runner PID timestamps.

If the browser installation has no safe programmatic tab-close mechanism, the exact-tab close/reload is the one manual action in this otherwise scripted sequence; record it explicitly.

## Close-out rule

Do not mark M0, M1, or M2 complete from source inspection, unit tests, or CI alone. Change the remediation checklist to `[x]` only when the corresponding live evidence artifact exists and is internally consistent.
