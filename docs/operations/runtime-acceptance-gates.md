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

For every prompt it verifies a terminal `complete` operation, checks that the unique marker is contained in the response text, and verifies the exact +1 user/+1 assistant progression from the durable `chatgpt_response` evidence record. The native controller persists those progression counts in a per-conversation ledger keyed by completed operation IDs, because ChatGPT can virtualize older message nodes out of the DOM; the ledger is seeded from the current conversation only and advances exactly once per completed prompt. That durable record survives a browser-page reload through the native recovery path. The conversation URL must remain unchanged for all 20 operations. Do not send human messages, edit the composer, or otherwise interact with the ChatGPT page during the 20-operation chain.

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

The harness uses the existing managed runtime directory (by default `$HOME/.pasi/overnight`; override with `PASI_RUNTIME_DIR`), starts one isolated 168-hour runner task without pushing its worktree branch, and records the exact operation ID and current ChatGPT conversation signature.

The sequence is deliberately fail-closed:

1. Preflight requires an authenticated, usable current ChatGPT conversation and a clean managed runner/supervisor. If port 8765 is already healthy, the harness adopts the existing bridge only when the listening process is a PASI bridge/router whose working tree contains `automation/orchestrator/bridge.py`; an unrelated listener remains a hard failure.
2. The harness waits until its exact prompt operation is `claimed` or `generating`.
3. It pauses for one manual action: close or reload the **exact ChatGPT conversation tab carrying that operation**. No replacement tab or human message is allowed.
4. It terminates only the managed bridge PID tree, waits for the bridge to become unavailable, restarts the same bridge runtime, and verifies the original operation ID still exists and is non-terminal.
5. It terminates only the managed runner PID tree. The test sets `PASI_SUPERVISOR_MAX_RESTARTS=0` so the supervisor cannot silently hide the runner kill with an automatic replacement.
6. It resumes with `bash scripts/start_pasi_168h.sh --resume --no-push` using the exact persisted branch/worktree identity.
7. Resume evidence must explicitly say `Resuming persisted ChatGPT operation: <original-id>`; a new `Prompt operation` ID or a `Retry prompt operation` is a failure.
8. Final evidence must show the same operation ID completed, the same ChatGPT conversation URL, the required unique marker, durable `user_messages_added: 1`, verified acknowledgement, and an exact +1 user/+1 assistant conversation-signature progression from the pre-operation baseline.

The harness writes an evidence artifact even on failure:

```
.runtime/acceptance/m2-live-*.json
```

The artifact records the stage that failed, operation snapshots, baseline/final conversation signatures, exact conversation URL, bridge/runner PID timestamps, resume output, and final response evidence. It must report `status: PASS` before M2 can be marked complete.

## Close-out rule

Do not mark M0, M1, or M2 complete from source inspection, unit tests, or CI alone. Change the remediation checklist to `[x]` only when the corresponding live evidence artifact exists and is internally consistent.
