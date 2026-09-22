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

The browser-health observation must identify the native controller and match the extension version in `automation/chromium/pasi-chatgpt/manifest.json`.

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

The evidence file is created at the beginning and updated after every completed operation. A mid-run transport, completion, marker, or signature failure leaves a machine-readable `FAIL` artifact with the completed count and partial results instead of disappearing into terminal output.

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

1. Wait until the exact operation is `claimed` or `generating` and verify `.runtime/chatgpt/session.json` durably names that same operation.
2. Close or reload the exact ChatGPT conversation tab carrying the operation. Never substitute another ChatGPT tab. Press Enter after the manual action so it is explicitly recorded in the evidence.
3. Kill the managed bridge process identified by `.runtime/overnight/bridge.pid`, wait for bridge health to return, and verify the same operation ID and durable handoff survived.
4. Kill the managed runner process identified by `.runtime/overnight/runner.pid`, then resume it with `bash scripts/start_pasi_168h.sh --resume`.
5. Verify the resumed runner still observes the same operation ID and handoff before waiting for terminal completion.
6. Verify the final response belongs to that exact operation, the conversation signature moved exactly +1/+1, and the active-operation checkpoint is cleared after terminal completion.

The generated M2 artifact is `.runtime/acceptance/m2-live-*.json`. It records the operation identity, pre/post conversation signatures, exact conversation URL, durable handoff snapshots, manual recovery record, and bridge/runner restart timestamps.

M2 is invalid when the operation becomes terminal before the bridge/runner recovery sequence begins; this prevents a fast response from being mistaken for a successful restart-recovery test.

If the browser installation has no safe programmatic tab-close mechanism, the exact-tab close/reload is the one manual action in this otherwise scripted sequence; record it explicitly.

## Close-out rule

Do not mark M0, M1, or M2 complete from source inspection, unit tests, or CI alone. Change the remediation checklist to `[x]` only when the corresponding live evidence artifact exists and is internally consistent.

## Final artifact validation

Before changing any P0 checklist item to `[x]`, validate the live evidence set with:

```bash
python scripts/validate_p0_acceptance_artifacts.py \
  --runtime-dir "$HOME/.pasi/overnight" \
  --require-live-gates
```

The validator fails closed when M0/M1/M2 evidence is missing, when M1 does not contain exactly 20 unique complete operations with +1/+1 deltas, when M2 loses exact operation/conversation identity or restart proof, or when P0.4 lacks a strict 168-hour PASS with verified branch, clean worktree, historical resource samples, and PR provenance.

M0/M1/M2/P0.4 remain live-runtime acceptance gates. Passing the artifact validator alone does not create missing evidence.