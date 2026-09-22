# Experiment Lab and Host Capability Architecture

## Purpose

PASI should become a practical engineering experimentation environment, not only a planner and automation shell. The Experiment Lab groups simulation, modeling, fuzzing, live host observation, resource profiles, hardware-aware execution modes, and model/provider capacity behind explicit application boundaries.

The Lab has two distinct planes:

1. **Experiment plane** — deterministic calculations, simulations, model planning, and bounded fuzzing. These operations are reproducible, inspectable, and provider-independent.
2. **Host plane** — live observation of system and process resource usage plus narrowly scoped resource controls. Observation can cover unrelated host programs; mutation requires an explicit PASI permission and an OS capability check.

## Resource-control contract

PASI may observe host processes without requiring the target program to be a PASI project. A process row should expose PID, command/name, resident memory, swap use, thread count, and sampled timestamp.

Resource mutation is never performed through arbitrary shell commands. The first implementation uses Linux cgroup v2 when a delegated writable hierarchy is available. PASI refuses to modify PID 0, PID 1, or its own server process. When cgroup delegation is unavailable, the UI reports that limitation instead of pretending that a limit was applied.

Profiles are modeled as requested resources rather than permanent edits to the target application. The UI provides Preview, Apply, and Clear operations, and the backend reports whether the OS actually accepted the change.

## Immediate feedback loop

The web client polls host telemetry on a short interval while the Lab is visible. The client keeps the previous sample and renders changes in memory/swap/load next to the selected process. A future native host agent can provide faster event-driven sampling and Windows process control without changing the UI contract.

## Higher-power execution tiers

Hardware profiles are capabilities, not hard-coded machine classes:

- **Easy** — conservative local model/simulation/fuzz settings.
- **Standard** — larger local workloads.
- **Performance** — higher concurrency, larger fuzzing batches, larger model context, and more aggressive simulation budgets.
- **Max** — opt-in resource-heavy local execution with visible safeguards.

The backend should report actual host capabilities before enabling a tier. A tier never silently bypasses correctness, verification, security, or provider cost boundaries.

## Models and paid providers

Local models remain the default free-first route. The existing provider-neutral connection/plugin boundary is extended in the UI so a user can register a paid provider and choose it for a workload without tying core engineering functions to that vendor.

API credentials should stay in the provider/host credential mechanism rather than browser localStorage. The browser sends provider identifiers and capability choices; secrets stay behind the local service boundary.

## Fuzzing

Fuzzing is initially constrained to registered deterministic calculations and simulations. A seeded mutator creates numeric inputs, runs the selected target, captures successes and failures, and returns a fingerprint. This creates a testable foundation for larger property-based and domain-specific fuzzing later without granting arbitrary code execution.

## Extension alignment

The browser extension remains a presentation/control surface, not the source of truth for execution. The same Lab contracts can be surfaced in the native Chromium extension popup/side panel later. Browser actions that trigger expensive or paid work should pass through the existing authorization and provider boundaries.

## Acceptance targets

A complete future Lab should make it possible to:

- inspect host utilization and unrelated processes live;
- preview and, where the OS permits, apply RAM/swap profiles;
- compare before/after telemetry around a workload;
- build deterministic engineering model plans;
- execute and compare simulations;
- run seeded fuzzing at a bounded scale;
- select higher-capacity local execution profiles based on detected hardware;
- register and select paid APIs/models without hard-wiring a vendor into PASI;
- preserve verification, audit, and cost controls across every mode.
