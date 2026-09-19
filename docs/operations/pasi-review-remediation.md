# PASI Review Remediation Diagnostic

## Purpose

Persistent recovery/checkpoint for the external review remediation checklist. This file is the authoritative handoff point when work stops unexpectedly. Read **Current Step** first, then continue from that checklist item and gate.

## Current Step

**M0 / T1-T4 — in progress.**

Immediate work:
1. Preserve assistant response line breaks so machine-readable PASI markers and unified diffs survive browser extraction.
2. Feed the validated patch to `git apply` through stdin in the shared engine path.
3. Add seam/regression coverage for extraction, parsing, patch application, and commit flow.
4. Remove the native-path hard dependency on the legacy controller-distribution service at `127.0.0.1:8766`.

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
- [ ] T1 response extraction preserves line breaks; collapsed text is fingerprint-only; multiline fixture round-trips.
- [ ] T2 shared `git apply --check -` / `git apply -` path accepts a patch on stdin and rejects invalid patches.
- [ ] T3 seam test proves browser-format response → parser → patch application/commit path.
- [ ] T4 native launcher/engine no longer requires `:8766`; native version comes from native extension manifest/controller.

**M0 Gate:** one real task on a scratch repository reaches ChatGPT response → parser → patch applied → validation → commit.

### M1 — False Verdicts / Duplicates
- [ ] T5 scoped detectors; no body/sidebar false positives; Python phrase lists removed; raw provider errors not re-injected.
- [ ] T6 operation nonce + acknowledgment; no reinsert while generating/bubble count changed.
- [ ] T7 stable completion (stop button gone + 3–5s stability + final marker).
- [ ] T8 exact new-chat control + emptiness verification.
- [ ] T9 single controller-tab election.

**M1 Gate:** 20 consecutive prompts, zero false terminal `CHAT_*` verdicts, zero duplicate user messages.

### M2 — Timeouts / State
- [ ] T10 shared timeout table and heartbeat alarm.
- [ ] T11 bridge claim lease/reclaim, queue TTL, cancel endpoint, POST-only claim path, traceback logging.
- [ ] T12 separate retry budgets by failure class.
- [ ] T13 recovery-state consistency, missing-op expiry, fresh-chat GitHub reattachment, dead-hook removal.
- [ ] T14 watchdog uses queue status; health and state have separate slots.

**M2 Gate:** scripted kill/restart tests at tab, bridge, runner stages produce zero duplicate prompts.

### M3 — Continuation
- [ ] T15 validated NEXT_TASK + durable task ledger + evidence-driven gate + explicit precedence for task sources.
- [ ] T16 v1 folded into v2; no monkeypatch/pass-through wrapper.

**M3 Gate:** 10-task run produces no repeated task text and no redo commits.

### M4 — Security
- [ ] T17 bridge launch token + JSON content type + Host/Origin validation.
- [ ] T18 protected paths and resolved Git paths/mode/rename validation.
- [ ] T19 validation sandbox with environment allowlist and no network/push credentials.
- [ ] T20 documented provider order; restricted OpenCode; no private code to free-tier providers.

**M4 Gate:** red-team checklist passes.

### M5 — Redundancy / Tests
- [ ] T21 one detector / one completion owner / one response store; legacy Tampermonkey pieces isolated/removed; dead code removed.
- [ ] T22 browser/DOM fixtures replace source-regex tests; mutation checks.
- [ ] T23 documentation reconciled and complete bundle.

**M5 Gate:** final bundle contains all intended modules, tests, and consistent documentation.

## Resume Instructions

When asked "what step are we on?", report the unchecked item under **Current Step** and its associated gate status. If the last action failed, report the exact failing command/test and do not pretend the next step passed.

## Evidence Log

- 2026-09-19: external review identified T1-T4 blockers and M1-M5 follow-on issues.
- 2026-09-19: T1 implementation started; T2 implementation started; T4 implementation next.
