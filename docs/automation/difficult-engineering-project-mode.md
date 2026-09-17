# Difficult Engineering Project Mode

This mode defines the intended workload for unattended PASI engineering runs.

## Objective

PASI should work on substantial engineering problems rather than defaulting to small read-only inspections, documentation-only edits, tiny cosmetic changes, or trading-information research.

## Required behavior

A difficult engineering task should normally require the agent to:

1. Understand the existing architecture and relevant runtime behavior.
2. Form a concrete implementation plan before changing code.
3. Implement a meaningful capability or solve a meaningful defect, potentially across multiple modules/files.
4. Exercise the implementation with deterministic tests or other reproducible verification.
5. Inspect the resulting repository state and integration behavior.
6. Continue iterating when verification exposes a defect instead of stopping at the first plausible patch.
7. Produce a concise evidence record describing what changed and how it was verified.

## Scope preference

Prioritize work that advances the Computer-Use Control Plane and the infrastructure that makes it faster to build the rest of PASI: computer/browser control, ChatGPT/Claude/provider coordination, VS Code and terminal operation, state continuity, response/completion detection, recovery, orchestration, verification, memory, and research/evidence integration.

Do not choose trading or market-information work as the default engineering workload. Finance remains an information/analysis capability with human decisions and execution.

## Anti-triviality rule

Do not satisfy an engineering task solely by reading files, producing an explanation, editing README/docs only, changing comments, or making a cosmetic/no-op modification. A documentation-only change is appropriate only when the task itself is explicitly documentation work.

When the task is ambiguous, prefer the highest-value concrete implementation that can be safely verified in the repository.

## Safety

Never weaken authentication, authorization, path restrictions, network restrictions, approval boundaries, human control, or verification requirements in order to increase autonomy.
