# PASI PR Reconciliation — 2026-09-20

## Consolidated target

All reconciled work is being assembled on:

- Branch: `pasi/overnight-20260919-095554-751099426`
- Consolidated PR: #233
- Current reconciled head: `835cc43ddb27df11bdb15574df634568b0f20eed`
- Base: `main`

The purpose of this branch is to preserve useful work from the open PR set without blindly merging divergent histories. Each PR is classified below as integrated, equivalent/already present, selectively integrated, or intentionally not adopted.

## PR-by-PR disposition

| PR | Area | Disposition | Reconciliation result |
| --- | --- | --- | --- |
| #191 | PR scope governance | Integrated | Added `.github/pull_request_template.md` and `docs/operations/pr-scope-policy.md`. |
| #193 | Legacy Tampermonkey watchdog isolation | Integrated | Moved the runtime watchdog and its test under `automation/legacy/tampermonkey/`; CI now executes its relocated contract test. |
| #194 | Promotion/reopen/risk gates | Selectively integrated | Added change-count/scope gates, expanded high-risk paths, and permanent closed-PR handling. Retained the existing pre-auto-merge check gate instead of adopting immediate auto-merge, so PASI observes reported checks before requesting GitHub auto-merge. |
| #202 | Patch boundary/delete/ignored paths | Already integrated | The consolidated engine delegates to the legacy validator, which already contains ignored-path, deletion, symlink/submodule, protected-path, and credential-boundary checks. |
| #203 | Immutable trusted control tooling | Already integrated | The v2 runner resolves guard/router/promotion tooling from the launcher checkout and passes the isolated worktree as data; provider fallback credentials are scrubbed from the delegated environment. |
| #206 | Structured ChatGPT retry class | Integrated | Bridge retry classification already persisted structured retry classes; the ChatGPT adapter now also consumes `retry_class=context` and wrapped context-exhaustion failures. |
| #207 | No-change completion evidence | Integrated/strengthened | v2 no-change completion now requires concrete evidence and a durable completed-task ledger entry for the task being skipped. |
| #208 | Extension timeout-policy resource | Integrated | Added `timeout-policy.json`, packaged it as a web-accessible MV3 resource, and load it through `timeout-config.js`. |
| #209 | Controller lease serialization | Integrated | Restored the MV3 controller lease to #233 and serialized concurrent storage claims with a promise tail to avoid simultaneous leaders. |
| #210 | Stale recovery-operation expiry | Integrated/corrected | Recovery now records temporary lookup loss and clears the stale recovery/active markers after the 60-second grace period instead of retaining the state indefinitely. |
| #211 | ChatGPT connection-loss recovery | Integrated/corrected | Explicit `connection_failure` is actionable even when the observation heartbeat is still fresh; the stale-only ordering in the side PR is not retained. |
| #233 | Consolidated resilience/control-plane branch | Authoritative target | Contains the reconciled implementation, tests, prompt compiler integration, and operational safeguards. |
| #234 | Latency/prompt optimization | Selectively integrated | Fast normal-path timing, shared timeout policy, operator task override, and policy-driven browser/recovery behavior were integrated. The side PR's prompt-bloat reduction was not copied because `scripts/pasi_prompt_compiler.py` is now the authoritative prompt layer and preserves the user's multiline task-specific continuation format plus required execution context. |

## Prompt authority

`scripts/pasi_prompt_compiler.py` is the single prompt-construction authority for v2 unattended work.

The task payload remains multiline and is bounded without flattening its structure. The generated task follows:

```
CONTINUE WORKING ON THE CURRENT TASK:
<task-specific requirements, acceptance, constraints, context>

DO NOT STOP UNTIL YOU ARE FINISHED.
```

The compiler also injects deterministic run metadata, roadmap context, recent task history, failure evidence, completion markers, and security/verification rules. The runner logs the prompt pattern version and SHA-256 prompt hash.

The separate `continuation_directive()` helper in v2 now mirrors the same semantics rather than carrying a second roadmap/prompt policy.

## Browser control-plane alignment

The native extension now uses one shared timeout policy:

- controller poll: 500 ms
- DOM poll: 20 ms
- click settle: 20 ms
- response settle: 20 ms
- submission acknowledgement: 1000 ms
- Thinking verification: 3000 ms
- generation/recovery trigger ceiling: 3600 seconds
- recovery grace: 600 seconds

The 10–20 ms values are therefore used only on the successful response-to-next-prompt path; they are not used as unsafe long-response timeouts.

The native controller still uses bounded send attempts (3) and must never fire a second send strategy after one has already fired. Immediate terminal polling remains event/microtask driven.

The extension has:

- MV3 permissions limited to `alarms` and `storage`
- loopback bridge access confined to the service worker
- an explicit controller lease
- exact-chat identity recovery
- bounded tab refresh/recreation
- explicit connection-failure handling
- context/usage/auth distinction
- stale-operation recovery with a bounded expiry

Authentication and security challenges remain a human-control boundary; PASI does not bypass them.

## Verification changes included in reconciliation

The consolidated branch now contains regression coverage for:

- promotion size/scope/high-risk gating and closed-PR behavior
- structured retry classification in the ChatGPT adapter
- durable no-change completion evidence
- MV3 timeout-policy packaging
- shared timeout-policy consistency between browser JSON and Python loader
- controller lease serialization
- fresh-observation connection-failure recovery
- bounded stale-operation expiry
- prompt compiler multiline preservation and deterministic hashing
- policy-driven browser latency assertions

The repository's broad `scripts/check_all.sh` gate remains the canonical local validation command; the GitHub workflow also runs targeted computer-use, browser-recovery, prompt-submission/chaining, Tampermonkey, syntax, and browser-use compatibility checks.

## VS Code / WSL transfer

Use the reconciled branch directly:

```bash
cd ~/workspace/personal-ai-system

git fetch origin --prune
git switch pasi/overnight-20260919-095554-751099426
git pull --ff-only origin pasi/overnight-20260919-095554-751099426

git status --short
git rev-parse HEAD

bash scripts/check_all.sh
```

Expected branch head after this reconciliation: `835cc43ddb27df11bdb15574df634568b0f20eed`.

The VS Code checkout should use this branch as the source of truth for continued implementation. Runtime state under `.runtime/` remains generated/ignored state and is not part of the source transfer.

## Remaining acceptance boundary

The code reconciliation is complete at the source level, but the latest reconciled head still requires fresh CI and live browser acceptance before anyone should describe the 168-hour run as fully qualified. A previously green CI run exists on an older #233 head; it does not certify this new head.

When fresh CI is green, the side PRs whose changes are fully represented can be closed as superseded without losing their code because the reconciled commits live in #233.
