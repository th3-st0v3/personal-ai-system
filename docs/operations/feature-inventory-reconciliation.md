# PASI Feature Inventory Reconciliation

This document reconciles the current PASI feature inventory against the repository's implemented architecture. Items are classified as **implemented**, **implemented with a safer architectural form**, **deferred**, **operator-owned**, or **not adopted**. The inventory is treated as design input, not as an instruction to add technically unsafe or redundant mechanisms.

## Implemented

- **Deterministic-first Hybrid Planner** — PR #242 provides dependency validation, eligible-task filtering, optional AI ranking/decomposition, roadmap persistence, and executor/scheduler separation.
- **Response-to-next-prompt latency instrumentation** — runtime telemetry and the native controller record response completion, prompt dispatch/injection, bridge acknowledgement, and browser-generation timing. The normal-path target is measured in milliseconds rather than seconds; recovery ceilings remain bounded in seconds/minutes.
- **Cryptographic/serialized controller leases** — the native extension serializes controller claims and refreshes a bounded lease so only one controller instance owns active automation.
- **Durable evidence/task ledger** — completed work and execution evidence are persisted and reused for continuation/recovery decisions.
- **Completion effort floor** — PR #245 rejects thin new-task completion claims instead of allowing low-content answers to advance the scheduler.
- **Protected unattended runtime boundary** — PR #246 expands the protected patch surface around the complete 168-hour execution chain.
- **168-hour safety gate** — the supported unattended launcher is bounded to a 168-hour execution window; completion/interruption state is persisted rather than silently extending the same run.
- **Durable 168-hour handoff** — PR #248 persists a bounded handoff artifact at normal finish, interruption, and top-level failure.
- **Browser observation normalization** — PR #247 keeps downstream ChatGPT state handling compatible with both supported observation kinds.
- **Native Chromium controller** — the native extension is the preferred controller path; the Tampermonkey controller remains an alternate compatibility path rather than a second simultaneously active controller.
- **Control Center side panel foundation** — PR #244 adds roadmap import, dependency-aware ordering controls, controller/bridge telemetry, and local hardware-profile preference display without adding broad permissions or unsafe provider/process control.
- **Blast-radius/impact audit** — the repository already has an observational PR impact workflow that reports commits, files, line changes, scopes, directory footprint, and largest file deltas.
- **Runtime efficiency report** — existing telemetry reports repeated task numbers, short-response streaks, evidence thickness, recovery events, prompt sizes, and response-to-next-dispatch latency.
- **Provider fallback boundary** — the repository already has a bounded provider router and local-provider fallback path; provider output remains subject to the same completion and verification contracts.
- **Adversarial modification audit** — the repository has an isolated self-modification audit workflow and a protected unattended patch boundary for controller/runtime/workflow changes.
- **Manifest capability validation** — an explicit native-extension capability contract checks Chrome API use, permission coverage, host coverage, and the Python↔localhost bridge boundary without broadening permissions.
- **Self-hosted runner capability reconciliation** — the desired runner environment is versioned, detected, bounded, optionally repaired, and exposed through sanitized bridge telemetry; GitHub has a dedicated dispatchable reconciliation workflow.
- **Read-only runner state + safe Control Center controls** — the side panel can see the actual runner phase/task/resource state and request only a task-bound retry or a PASI-identified supervised stop.
- **Live WSL resource telemetry** — the capability report records total, available, and used memory plus CPU/swap values, allowing the UI to display the enforced 3 GiB / 2 CPU / 0-swap boundary with actual usage.
- **Optional provider expansion** — Groq and Gemini are implemented as bounded OpenAI-compatible adapters behind the same fallback/completion contract; credentials remain environment-only.
- **Repository secret scan** — a tracked-file high-confidence secret scanner is covered by tests and the security workflow.
- **Security automation** — CodeQL, dependency audit, and Dependabot configuration are now repository-managed security controls.
- **Deterministic run storyteller** — durable state, handoff, and recovery events can be rendered as a bounded human-readable run narrative.
- **WSL resource boundary** — the current development environment uses the documented 3 GiB WSL / 0 swap / 2 CPU constraint as an operator-level resource boundary.

## Implemented with a safer architectural form

- **Ephemeral supervisor** — PASI keeps a persistent runner state, lock, ledger, and supervisor because unattended continuity requires durable control state. Expensive validation/helpers are already short-lived subprocesses, which captures the memory-reclamation goal without destroying scheduler state after every task.
- **Substantiality guard** — the system does not use raw token-per-second as a hard correctness gate. Short responses are recorded as attention signals, while the completion effort floor and deterministic verification decide whether a task is allowed to advance.
- **Authenticated DOM mirroring** — the authoritative state path is a bounded browser observation contract over the localhost bridge; duplicating the full DOM in another process is intentionally avoided.
- **SharedArrayBuffer pipeline** — cross-process communication uses the existing authenticated localhost bridge and serialized JSON contracts. SharedArrayBuffer is not used as a Python↔Chrome IPC layer.
- **MessagePack DOM transfer** — not needed because PASI does not mirror/transmit full DOM trees across the control-plane boundary.
- **Task churning guard** — the existing roadmap loop guard, unique-task selection, retry-cycle retention, durable ledger, short-response telemetry, and completion effort floor already address the failure mode without adding a second competing scheduler.
- **Automatic PR autosplitting** — scope and promotion policy remain explicit. Security/runtime/control-plane changes retain their review boundary rather than being silently exploded into many automatically promoted PRs.
- **Ghost dissection retry** — planner/dissection failures are bounded and validated by the backend contract; the UI retry button does not become a second scheduler.
- **Panic/force skip** — panic stop is now available through the authenticated Control Center, but force-skip remains planner-owned so a UI action cannot bypass verification or dependency rules.
- **Hardware profile toggle** — the Control Center stores a local preference, but hardware profiles do not override the enforced WSL/runtime safety boundary.
- **AST modification shield** — protected runtime/controller paths are denied to unattended patches before application. A future AST-level semantic detector can add another review layer, but duplicating the same path guard is not necessary for the current M0/M1/M2 gate.

## Deferred

These are useful future work, but they should follow live M0/M1/M2 acceptance rather than precede it.

- **Idempotency replay simulation** — existing bridge tests cover response-loss/idempotent replay behavior; a dedicated live M2 harness remains a runtime acceptance task.
- **Visual telemetry barometer** — the panel now consumes authenticated runner RAM/capability telemetry; richer historical charts remain optional after live acceptance.
- **Dissection progress UI** — the current side panel can display roadmap/task state, but authoritative multi-pass cloud dissection progress should not be fabricated before a stable dissection service exists.
- **Speculative branching and large in-memory vector caches** — intentionally postponed until higher-memory profiles are real, measured, and justified by a demonstrated workload.

## Operator-owned

These settings are real environment controls rather than native extension capabilities and should be configured deliberately outside the unattended code path.

- **Opera GX RAM limiter** — browser memory limiting belongs to the browser/desktop environment; the repository should observe resource pressure rather than assume it can enforce the setting.
- **Opera GX CPU limiter** — same boundary as RAM limiting; do not grant the extension host-level resource-control privileges.
- **Battery-saver/background-throttling policy** — browser power-saving behavior is an operator/browser setting and should be verified separately before a long run.
- **Inactive-tab snoozing/suspension** — tab lifecycle policy must preserve the authoritative ChatGPT automation tab; aggressive suspension is not a correctness prerequisite.
- **Process recycling** — already used at the application boundary through short-lived validation/helper subprocesses rather than by destroying the persistent scheduler.

## Not adopted

- **Network stream/SSE interception for [DONE]-driven control** — the extension remains DOM/bridge based; the current architecture does not depend on reading model transport bodies at the extension network layer.
- **Host-level RAM/CPU enforcement from inside the extension** — WSL and browser resource limits are operator/environment concerns, not privileges granted to the native extension.
- **Automatic browser tab destruction/suspension as a core correctness mechanism** — tab lifecycle recovery exists, but discarding the authoritative ChatGPT page would undermine the continuity the controller is designed to preserve.
- **NVIDIA NIM as a permanent free provider** — not part of the accepted provider plan.
- **Multi-browser/headless speculative parallelism** — not part of the unattended control-plane design because it increases resource pressure and complicates state ownership.

## Inventory completion follow-up

The follow-up inventory branch adds durable engineering primitives without changing the primary browser-control boundary:

- `scripts/pasi_dissection_adapter.py` provides deterministic deconstruction, dependency mapping, and JSON compilation for raw roadmaps, with an optional AI-enrichment hook that must preserve task identity.
- `scripts/pasi_evidence_vault.py` provides an SQLite/WAL evidence store for task provenance alongside the existing JSON state/ledger.
- `scripts/pasi_idempotency_replay.py` provides a deterministic replay harness for duplicate-submission prevention.
- `scripts/pasi_semver.py` provides deterministic SemVer bumping and changelog generation from Conventional Commit subjects.
- `docs/operations/pasi-feature-inventory.json` makes the full inventory machine-readable for automation and VS Code reconciliation.

API credentials remain environment-only. The extension does not gain host-process, browser-network interception, SharedArrayBuffer, full-DOM mirroring, or arbitrary resource-control privileges.

## Current implementation priority

The repository should now optimize for a small number of hard acceptance gates rather than accumulating architecture:

1. **M0 live task:** one real task through response, parse, patch application, deterministic verification, and commit.
2. **M1 live chaining:** 20 consecutive prompt/response cycles with exact conversation-signature progression.
3. **M2 live recovery:** kill/restart and exact-operation reconciliation.
4. **Only after M2:** expand provider routing, UI telemetry, replay simulation, and other optional performance features.

## CI note

The current open PRs have repeatedly produced GitHub Actions jobs that terminate before executing workflow steps and without retrievable runner logs. GitHub's public status page currently reports Actions as operational and shows no incident for September 21, 2026. citeturn789702search0 That leaves the repository's pre-step failures as an unresolved CI execution gate rather than evidence that the code has passed. Those PRs should remain unmerged until an executable green CI result exists.