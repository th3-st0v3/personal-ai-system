# Free Validation Contract

PASI's deterministic validation path must be sufficient to exercise production behavior without consuming paid model/provider usage or depending on metered GitHub-hosted runner capacity.

The required `free-validation` CI gate runs on the repository's self-hosted `pasi-wsl` runner by default. An explicit manual `workflow_dispatch` choice can route the same job to `ubuntu-latest`; normal PR, push, and scheduled validation remains self-hosted. GitHub documents self-hosted runner execution as free of Actions minutes, while private-repository GitHub-hosted runners consume the account's included minutes and can be blocked when quota/payment requirements are exhausted.

## CI runner selection

The test workflow defaults every test job to the self-hosted `pasi-wsl` runner and runs a runner preflight before the suite. The preflight can be checked locally with:

    python scripts/check_pasi_self_hosted_runner.py

The workflow has one explicit `workflow_dispatch` choice, `runner_mode`: `self-hosted` is the normal/default path and `github-hosted` is the deliberate fallback for the period after GitHub-hosted Actions usage limits or payment restrictions have been cleared. The fallback is never automatic, because an automatic fallback would reintroduce the billing failure this contract is intended to prevent. GitHub supports selecting runners with expressions and self-hosted labels in `runs-on`. citeturn689956search0turn689956search1

## Required test tiers

1. Static and unit validation — syntax, types, contracts, pure decision logic, parser/guard behavior, and individual controller modules.
2. Local interaction validation — real production modules connected to deterministic fake transports, local bridge fixtures, browser DOM fixtures, persisted state, queue state, retry/recovery transitions, and failure injection.
3. Browser fixture acceptance — the real native Chromium extension is loaded into a locally controlled Chromium-family browser against a local HTTPS ChatGPT fixture and a randomly allocated loopback bridge port. No ChatGPT account, prompt, model generation, or paid provider request is involved.
4. Live acceptance — optional operational verification only. It is never the sole evidence for a code change that can be covered by the deterministic tiers.

## Isolation requirements

Free tests must not bind the production bridge port when a random loopback port can be used. Test-staged extensions may rewrite the bridge endpoint and host permission for the fixture only.

Free tests must set PASI_FREE_TEST_MODE=1. Provider-router code must reject non-loopback HTTP(S) calls while that mode is active, so an accidental API-provider path cannot create billable traffic.

Live ChatGPT and API credentials must never be required for the deterministic test tiers. Existing credentials in the shell must not change whether the tests execute the local fixtures.

## Interaction coverage

Changes that cross component boundaries must add or reuse a deterministic scenario that exercises the complete seam, for example:

- adapter -> bridge -> browser controller -> DOM -> recovery state -> bridge acknowledgement
- queue -> operation claim -> prompt injection -> response detection -> completion persistence -> next-operation handoff
- heartbeat -> stale/connection failure -> watchdog -> bounded reload -> recovery state -> exact operation resumption
- provider router -> provider response parser -> PASI result contract -> verification gate

A unit test that only mocks the boundary is not sufficient when the change modifies the interaction itself.

## Required developer entry point

Use:

    python scripts/run_free_acceptance.py

This command enables free-test isolation, runs the repository validation suite, then executes the local browser fixture acceptance tests. A compatible non-Snap Chromium binary must be installed or supplied through PASI_E2E_CHROME_BINARY.

## Future-change rule

A future feature is not considered fully verified merely because its module test passes. Its changed seams must have a deterministic local interaction test, and any browser-facing behavior must have a local fixture acceptance path. Live provider usage is supplemental evidence, not the merge prerequisite for deterministic behavior.
