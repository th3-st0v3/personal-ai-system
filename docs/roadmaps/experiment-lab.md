# Experiment Lab Roadmap

## Goal

Turn PASI's web workspace and native browser extension into a practical local experimentation and performance-optimization environment.

The Lab should let a user make a change, run a controlled workload, see the effect immediately, compare against prior runs, and preserve enough evidence to reproduce the result.

## Phase 1 — Current vertical slice

Implemented on the Experiment Lab branch:
- deterministic calculations and simulations;
- deterministic engineering model planning;
- bounded seeded fuzzing;
- live Linux host and process telemetry;
- observation of programs that do not belong to a PASI project;
- explicit host-control permission;
- Linux cgroup v2 RAM/swap profiles where the OS delegates the capability;
- hardware-gated Easy / Standard / Performance / Max workload tiers;
- local Ollama model discovery;
- provider readiness without exposing API credentials;
- Experiment Lab navigation in the web workspace and native extension.

## Phase 2 — Measurement and optimization

Add a reusable experiment record:
1. capture baseline host/process telemetry;
2. apply one controlled change;
3. run the workload;
4. sample telemetry continuously;
5. compare before/after latency, CPU, RAM, swap, GPU, I/O, throughput, and error rate;
6. store the workload configuration, change, result, and fingerprint.

The Lab UI should visualize the result as a live time-series chart and an explicit before/after comparison rather than relying on a single current value.

## Phase 3 — Full host agent

The local web service should be able to talk to an OS-specific native host agent.

### Windows

- enumerate host-wide processes;
- process CPU/RAM/thread/I/O metrics;
- process affinity and priority where safe;
- Windows Job Objects or an equivalent supported resource boundary for managed workloads;
- WSL-to-Windows capability reporting;
- GPU/process telemetry where the vendor API permits it.

### Linux

- cgroup v2 workload groups;
- CPU affinity and quota;
- memory and swap controls;
- I/O controls where supported;
- per-process and per-cgroup telemetry.

### macOS

- observation through supported system interfaces;
- resource-control capabilities only where the operating system exposes a safe supported mechanism.

The host agent must be a narrow capability provider. It should not become an unrestricted command shell.

## Phase 4 — Advanced simulation and modeling

Add experiment composition:
- parameter sweeps;
- Monte Carlo runs;
- sensitivity analysis;
- uncertainty propagation;
- optimization loops;
- scenario comparison;
- numerical-method selection;
- model validation against reference data;
- result provenance and reproducible experiment packages.

The planner should be able to turn a natural-language engineering question into a structured experiment graph.

## Phase 5 — Advanced fuzzing

Expand beyond numeric mutation of deterministic models:
- boundary-value corpora;
- property-based tests;
- structured/domain-aware mutation;
- differential testing between independent implementations;
- invariant checking;
- NaN/infinity/overflow and precision stress;
- long-running campaigns with checkpoint/resume;
- corpus minimization;
- regression corpus generation.

Large campaigns remain bounded and must report their budget, seed, target, and resulting fingerprints.

## Phase 6 — High-capacity local execution

Detect actual machine capabilities rather than relying on a manually entered hardware class.

Possible capabilities include:
- available CPU cores and memory;
- GPU vendor/device and usable memory;
- local model inventory;
- simulation parallelism;
- available storage;
- vectorization/runtime features.

Higher tiers may unlock:
- stronger locally run coding models;
- larger model context;
- parallel model workers;
- larger simulation grids;
- higher fuzz budgets;
- more detailed sensitivity/Monte Carlo runs.

Higher tiers never bypass verification, safety, provider-cost controls, or authorization.

## Phase 7 — Native provider setup

Make provider setup easy from the web workspace and native Chromium extension without putting credentials in browser localStorage.

The intended flow:
1. choose Local or Hosted;
2. choose provider;
3. show required capabilities and cost metadata;
4. choose credential source;
5. validate connectivity;
6. select models;
7. run a small capability test;
8. save only non-secret configuration in PASI;
9. keep secrets in the local credential mechanism/environment;
10. make the selected provider/model available to eligible workloads.

The provider layer should remain vendor-neutral so adding or replacing providers does not change the planner, simulator, verifier, or UI contracts.

## Phase 8 — Closed-loop optimization

A future Optimization Lab can automatically explore safe parameter changes:
`baseline -> change -> workload -> telemetry -> compare -> keep/revert -> next candidate`

Only explicitly authorized resource controls and workload changes may be automated. Every experiment should produce a durable record that explains what changed and why a result was accepted or rejected.
