# PASI Feature Inventory Reconciliation

This document reconciles the current PASI feature inventory against the repository's implemented architecture. Items are classified as **implemented**, **implemented with a safer architectural form**, **deferred**, or **not adopted**. The inventory is treated as design input, not as an instruction to add technically unsafe or redundant mechanisms.

## Implemented

- **Deterministic-first Hybrid Planner** — PR #242 provides dependency validation, eligible-task filtering, optional AI ranking/decomposition, roadmap persistence, and executor/scheduler separation.
- **Response-to-next-prompt latency instrumentation** — runtime telemetry and the native controller record response completion, prompt dispatch/injection, bridge acknowledgement, and browser-generation timing. The normal-path target is measured in milliseconds rather than seconds; recovery ceilings remain bounded in seconds/minutes.
- **Cryptographic/serialized controller leases** — the native extension serializes controller claims and refreshes a bounded lease so only one controller instance owns active automation.
- **Durable evidence/task ledger** — completed work and execution evidence are persisted and reused for continuation/recovery decisions.
- **Completion effort floor** — PR #245 rejects thin new-task completion claims instead of allowing low-content answers to advance the scheduler.
- **Protected unattended runtime boundary** — PR #246 expands the protected patch surface around the complete 168-hour execution chain.
- **Durable 168-hour handoff** — PR #248 persists a bounded handoff artifact at normal finish, interruption, and top-level failure.
- **Browser observation normalization** — PR #247 keeps downstream ChatGPT state handling compatible with both supported observation kinds.
- **Native Chromium controller** — the native extension is the preferred controller path; the Tampermonkey controller remains an alternate compatibility path rather than a second simultaneously active controller.
- **Control Center side panel foundation** — PR #244 adds roadmap import, dependency-aware ordering controls, controller/bridge telemetry, and local hardware-profile preference display without adding broad permissions or unsafe provider/process control.
- **Blast-radius/impact audit** — the repository already has an observational PR impact workflow that reports commits, files, line changes, scopes, directory footprint, and largest file deltas.
- **Runtime efficiency report** — existing telemetry reports repeated task numbers, short-response streaks, evidence thickness, recovery events, prompt sizes, and response-to-next-dispatch latency.
- **Provider fallback boundary** — the repository already has a bounded provider router and local-provider fallback path; provider output remains subject to the same completion and verification contracts.
- **WSL resource boundary** — the current development environment uses the documented 3 GiB WSL / 0 swap / 2 CPU constraint as an operator-level resource boundary.

## Implemented with a safer architectural form

- **Ephemeral supervisor** — PASI keeps a persistent runner state, lock, ledger, and supervisor because unattended continuity requires durable control state. Expensive validation/helpers are already short-lived subprocesses, which captures the memory-reclamation goal without destroying scheduler state after every task.
- **Substantiality guard** — the system does not use raw token-per-second as a hard correctness gate. Short responses are recorded as attention signals, while the completion effort floor and deterministic verification decide whether a task is allowed to advance.
- **Authenticated DOM mirroring** — the authoritative state path is a bounded browser observation contract over the localhost bridge; duplicating the full DOM in another process is intentionally avoided.
- **SharedArrayBuffer pipeline** — cross-process communication uses the existing authenticated localhost bridge and serialized JSON contracts. SharedArrayBuffer is not used as a Python↔Chrome IPC layer.
- **MessagePack DOM transfer** — not needed because PASI does not mirror/transmit full DOM trees across the control-plane boundary.
- **Task churning guard** — the existing roadmap loop guard, unique-task selection, retry-cycle retention, durable ledger, short-response telemetry, and completion effort floor already address the failure mode without adding a second competing scheduler.
- **Automatic PR autosplitting** — scope and promotion policy remain explicit. Security/runtime/control-plane changes retain their review boundary rather than being silently exploded into many automatically promoted PRs.
- **Ghost dissection retry** — planner/dissection failures are bounded and validated by the backend contract; a UI retry affordance is not treated as the source of truth.
- **Panic/force skip** — the system prefers bounded recovery, retry, and durable task retention. There is no unrestricted UI path that can silently bypass verification or dependency rules.
- **Hardware profile toggle** — the Control Center stores a local preference, but hardware profiles do not override the enforced WSL/runtime safety boundary.

## Deferred

These are useful future work, but they should follow live M0/M1/M2 acceptance rather than precede it.

- **Groq/Gemini free-tier routing** — candidates for later provider expansion after the primary browser path and recovery gates are proven in live operation.
- **Idempotency replay simulation** — should be added as a dedicated live/recovery acceptance harness once M2 is passing consistently.
- **Automated storyteller** — human-readable commit summaries can be layered onto the existing impact/ledger data after core execution reliability is established.
- **Secret scanning and broader supply-chain scanning** — repository-level security automation remains a later hardening wave; it should not become a substitute for the existing runtime authorization boundary.
- **Extended dependency vulnerability automation** — evaluate Dependabot/CodeQL or equivalent integration as a separate security-focused change after the current CI execution problem is resolved.
- **Visual telemetry barometer** — the side panel foundation can consume stronger host/RAM/latency telemetry once an authenticated bridge contract exists for those fields.
- **Dissection progress UI** — the current side panel can display roadmap/task state, but authoritative multi-pass cloud dissection progress should not be fabricated before a stable dissection service exists.
- **Speculative branching and large in-memory vector caches** — intentionally postponed until higher-memory profiles are real, measured, and justified by a demonstrated workload.

## Not adopted

- **Network stream/SSE interception for [DONE]-driven control** — the extension remains DOM/bridge based; the current architecture does not depend on reading model transport bodies at the extension network layer.
- **Host-level RAM/CPU enforcement from inside the extension** — WSL and browser resource limits are operator/environment concerns, not privileges granted to the native extension.
- **Automatic browser tab destruction/suspension as a core correctness mechanism** — tab lifecycle recovery exists, but discarding the authoritative ChatGPT page would undermine the continuity the controller is designed to preserve.
- **NVIDIA NIM as a permanent free provider** — not part of the accepted provider plan.
- **Multi-browser/headless speculative parallelism** — not part of the unattended control-plane design because it increases resource pressure and complicates state ownership.

## Current implementation priority

The repository should now optimize for a small number of hard acceptance gates rather than accumulating architecture:

1. **M0 live task:** one real task through response, parse, patch application, deterministic verification, and commit.
2. **M1 live chaining:** 20 consecutive prompt/response cycles with exact conversation-signature progression.
3. **M2 live recovery:** kill/restart and exact-operation reconciliation.
4. **Only after M2:** expand provider routing, UI telemetry, replay simulation, and other optional performance features.

## CI note

The current open PRs have repeatedly produced GitHub Actions jobs that terminate before executing workflow steps and without retrievable runner logs. That is an execution/infrastructure gate, not evidence that the PR code itself is incorrect. Those PRs should remain unmerged until an executable green CI result exists.
