# Beta Implementation Status

This document maps the current implemented browser beta to the long-term requirements in `SYSTEM-REQUIREMENTS.md`. The master requirements remain broader than the current implementation; this file prevents that distinction from being confused with missing beta plumbing.

## Implemented now

- Persistent local project/workspace state.
- Arbitrarily nested folders with notes and files.
- File metadata/byte-storage separation.
- Project-scoped rename, move, copy/paste, duplicate, delete, lifecycle, and search operations.
- Project-scoped engineering requirements, sources, evidence, design cases, and decisions.
- Text, public GitHub-file, and PDF source ingestion with chunk/search retrieval.
- Deterministic calculation registry with parameter metadata, validation, traces, assumptions, limitations, and persisted calculation records.
- Deterministic simulation catalog and policy-gated simulation execution.
- Persisted chat with project association and lifecycle/feedback controls.
- Authentication boundary and local session handling.
- Controlled connections/plugins/source retrieval surfaces.
- Backend request-size and malformed-input guards.
- Cross-project isolation checks at application/API boundaries.
- CI coverage for Python tests, type checking, Markdown, browser JavaScript syntax, frontend/backend contracts, and Browser/API smoke tests.

## Required now but still actively evolving

- Broader learning, knowledge, and research workflows.
- Richer engineering canvas and visualization.
- More domain-specific engineering solvers and simulation backends.
- Stronger audit/event visibility across every sensitive action.
- Broader adversarial security and prompt-injection regression coverage.
- More comprehensive browser automation/E2E coverage across every production UI path.

## Eventually / later

The long-term document still governs multi-agent orchestration, advanced learning intelligence, broader engineering execution, HPC/accelerator scheduling, multimodal engineering canvas, deeper personalization, and controlled autonomy beyond the current beta.

Those future requirements must be implemented behind stable interfaces and must not be used as a reason to remove working beta capabilities.
