# PASI Review Remediation Diagnostic

## Purpose

Persistent recovery/checkpoint for the external review remediation checklist. This file is the authoritative handoff point when work stops unexpectedly. Read **Current Step** first, then continue from that checklist item and gate.

## Current Step

**M5 / T22-T23 — final verification in progress; implementation work is frozen pending CI and acceptance-gate evidence.**

Immediate verification sequence:
1. Confirm the stable branch head completes the canonical GitHub Actions suite without failures.
2. If CI is green, run/record the available real-Chromium baseline and mutation checks and inspect their diagnostics.
3. Verify the milestone gates that can be exercised in CI; explicitly leave only genuinely interactive ChatGPT-only gates pending if the environment cannot perform them.
4. Reconcile the final documentation/bundle inventory and record the exact head SHA here.
5. Do not restart implementation unless CI or acceptance evidence identifies a concrete defect.

## Already Verified Before This Remediation

- Native Chromium stale-focus / `aria-hidden` handling exists.
- Fresh-chat root-surface handling exists.
- Fresh runner worktrees now inherit launcher `HEAD` rather than silently starting from `origin/main`.
- The previous worktree regression test exposed and then corrected a missing test import.
- Current remediation branch starts from the fixed overnight branch rather than `c100c68`.

## Review Blockers From External Review

- T1: response line-break loss at browser extraction/parser seam.
- T2: patch never passed to `git apply`.
- T3: no browser → parser → apply/commit seam test.
- T4: native Chromium path coupled to legacy controller distribution.
- Subsequent M1-M5 items remain pending until each gate passes.

## Gate Policy

Do not mark a milestone complete from source inspection alone. Record deterministic test evidence or clearly record the environmental limitation. Do not advance past a failed gate without either repairing the failure or recording the exact blocker here.

## Checklist

### M0 — Unblock
- [x] T1 response extraction preserves line breaks; collapsed text is fingerprint-only; multiline fixture round-trips.
- [x] T2 shared `git apply --check -` / `git apply -` path accepts a patch on stdin and rejects invalid patches.
- [x] T3 seam test proves browser-format response → parser → patch application/commit path.
- [x] T4 native launcher/engine no longer requires `:8766`; native version comes from native extension manifest/controller.

**M0 Gate:** one real task on a scratch repository reaches ChatGPT response → parser → patch applied → validation → commit.

### M1 — False Verdicts / Duplicates
- [x] T5 scoped detectors; no body/sidebar false positives; Python phrase lists removed; raw provider errors not re-injected.
- [x] T6 operation nonce + acknowledgment; no reinsert while generating/bubble count changed.
- [x] T7 stable completion (stop button gone + 3–5s stability + final marker).
- [x] T8 exact new-chat control + emptiness verification.
- [x] T9 single controller-tab election.

**M1 Gate:** 20 consecutive prompts, zero false terminal `CHAT_*` verdicts, zero duplicate user messages.

### M2 — Timeouts / State
- [x] T10 shared timeout table and heartbeat alarm.
- [x] T11 bridge claim lease/reclaim, queue TTL, cancel endpoint, POST-only claim path, traceback logging.
- [x] T12 separate retry budgets by failure class.
- [x] T13 recovery-state consistency, missing-op expiry, fresh-chat GitHub reattachment, dead-hook removal.
- [x] T14 watchdog uses queue status; health and state have separate slots.

**M2 Gate:** scripted kill/restart tests at tab, bridge, runner stages produce zero duplicate prompts.

### M3 — Continuation
- [x] T15 validated NEXT_TASK + durable task ledger + evidence-driven gate + explicit precedence for task sources.
- [ ] T16 v1 folded into v2; no monkeypatch/pass-through wrapper.

**M3 Gate:** 10-task run produces no repeated task text and no redo commits.

### M4 — Security
- [x] T17 bridge launch token + JSON content type + Host/Origin validation.
- [x] T18 protected paths and resolved Git paths/mode/rename validation.
- [x] T19 validation sandbox with environment allowlist and no network/push credentials.
- [ ] T20 documented provider order; restricted OpenCode; no private code to free-tier providers.

**M4 Gate:** red-team checklist passes.

### M5 — Redundancy / Tests
- [x] T21 one detector / one completion owner / one response store; legacy Tampermonkey pieces isolated/removed; dead code removed.
- [x] T22 browser/DOM fixtures cover the native path; deliberate response-collapse mutation is expected to fail. Static regex tests remain as compatibility guards.
- [x] T23 active launcher/service/provider documentation reconciled; legacy compatibility docs isolated. Final CI/bundle verification remains.

**M5 Gate:** final bundle contains all intended modules, tests, and consistent documentation.

## Resume Instructions

When asked "what step are we on?", report the unchecked item under **Current Step** and its associated gate status. If the last action failed, report the exact failing command/test and do not pretend the next step passed.

## Evidence Log

- 2026-09-19: external review identified T1-T4 blockers and M1-M5 follow-on issues.
- 2026-09-19: T1-T4 implementation completed in source; end-to-end M0 gate still pending.
- 2026-09-19: T5-T15 implementation work completed in source; M1/M2/M3 gates still require deterministic and/or real-runtime evidence.
- 2026-09-19: T17-T19 implementation completed in source; T20 remains incomplete pending remote-provider privacy opt-in.
- 2026-09-19: latest checkpoint: M2/M3/M4 implementation and verification in progress.

- 2026-09-19: implementation frozen for final verification at branch head after T21/T22/T23 source changes; CI run 2363 is the current validation attempt.
