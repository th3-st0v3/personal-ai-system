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

## M1 — 20 consecutive prompts in the existing conversation

Run:

```bash
python scripts/run_m1_live_acceptance.py
```

The harness uses the already-open authenticated ChatGPT conversation. It does **not** call `new_session`, queue a `new_chat` operation, or replace the conversation at the beginning of the test. It sends exactly 20 uniquely marked prompts in that same conversation.

Before operation 1, the harness requires a usable current conversation: no verified conversation-context exhaustion, no provider usage limit, and a clean composer with no unsent human draft text. If the current conversation is already exhausted, or the composer contains unrelated draft text, M1 fails rather than replacing or overwriting the conversation state.

For every prompt it verifies a terminal `complete` operation, checks that the unique marker is contained in the response text, and verifies the exact +1 user/+1 assistant progression from the durable `chatgpt_response` evidence record. That durable record survives a browser-page reload through the native recovery path. The conversation URL must remain unchanged for all 20 operations. Do not send human messages, edit the composer, or otherwise interact with the ChatGPT page during the 20-operation chain.

M1 passes only when all 20 operations complete, every response contains its unique marker, each operation changes the signature by exactly +1 user message and +1 assistant message, zero terminal `CHAT_*` verdicts occur, and the final signature equals the baseline counts plus 20.

Evidence:

```
.runtime/acceptance/m1-live.json
```

The evidence records `created_new_chat: false`.

### Context-exhaustion recovery is a separate live behavior

PASI's recovery path is intentionally conditional: a replacement chat is prepared only after the browser verifies conversation-context exhaustion. Provider usage-limit exhaustion is handled separately and does not by itself justify deleting or replacing the current conversation.

Do not use M1 to simulate that condition by creating a new chat with usage remaining. A real context-exhaustion acceptance should begin from a verified exhausted conversation state, observe the recovery's reason as `context_exhausted`, verify the replacement `new_chat` operation, and then verify that the original operation is resumed exactly once in the replacement conversation. Unit tests can cover the branching logic, but only live browser evidence can close the live recovery gate.

## M2 — kill/restart recovery

Run:

```bash
bash scripts/run_m2_live_acceptance.sh
```

Record the printed `operation_id`. Exercise recovery against that exact operation in this order:

1. Close or reload the exact ChatGPT conversation tab carrying the operation. Never substitute another ChatGPT tab.
2. Kill the managed bridge process identified by `.runtime/overnight/bridge.pid`, wait for bridge health to return, and verify the same operation ID remains active/recoverable.
3. Kill the managed runner process identified by `.runtime/overnight/runner.pid`, then resume it with `bash scripts/start_pasi_168h.sh --resume`.

The terminal evidence must show the original operation ID was resumed/reclaimed exactly once, the original prompt was not submitted again, and the final response belongs to that same operation.

The generated M2 artifact is `.runtime/acceptance/m2-live-*.json`. Append the final operation JSON, before/after conversation signatures, the exact conversation URL, and bridge/runner PID timestamps.

If the browser installation has no safe programmatic tab-close mechanism, the exact-tab close/reload is the one manual action in this otherwise scripted sequence; record it explicitly.

## Close-out rule

Do not mark M0, M1, or M2 complete from source inspection, unit tests, or CI alone. Change the remediation checklist to `[x]` only when the corresponding live evidence artifact exists and is internally consistent.
