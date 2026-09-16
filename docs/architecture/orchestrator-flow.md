# PASI Orchestrator Flow

This document records the canonical order for the orchestrator so downstream features do not force avoidable rewrites.

## Canonical flow

```text
Task creation
  ↓
Precheck / project-state capture
  ↓
Research / evidence collection
  ↓
Context package assembly
  ↓
Planner request
  ↓
Planner result
  ↓
State transition
  ↓
Execution / verification (when authorized)
```

## Ordering rules

1. `CurrentTask` is the authoritative source for the active task objective. Downstream boundaries should use `task.objective` rather than maintaining another independently editable objective value.
2. Research happens before planner-facing context is finalized. Research may remain provider-independent and read-only, but its results should be available when the context package is assembled.
3. The context package is the provider-independent snapshot of project state presented to planning or other decision-making components. It is not a second durable research database.
4. Durable research state and the assembled context package remain separate artifacts. Research state preserves structured research; the context package contains the evidence selected for the current planning snapshot.
5. Planning remains non-executing. Execution and consequential actions belong to later capability/policy boundaries with explicit authorization and verification.
6. State transitions are recorded after the corresponding evidence and artifacts have been produced, so persisted state does not claim that a phase is complete before its output exists.

## Evidence and provenance

Research observations and findings should retain provenance, confidence, and verification status in durable research state. A flattened representation may be used for a consumer that only needs text, but the durable source should not discard source references or evidence semantics merely for convenience.

## Dependency boundaries

The orchestrator should depend on interfaces/protocols for research collection and planning rather than hard-coding concrete provider implementations into business logic. Temporary fake adapters are acceptable for scaffolding and tests, but the substitution boundary should be established before real providers are introduced.

## Current synchronization note

This architecture note is intentionally kept separate from the currently tested local work until the local `main` history is pushed. The remote repository must not be force-aligned to an unpushed local commit without first transferring the tested commit history.