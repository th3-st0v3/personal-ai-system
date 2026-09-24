# Canonical Operation State

PASI now has one versioned operation-state representation for control-plane lineage.

## Contract

The `automation/orchestrator/operation_state.py` module defines `OperationState` with schema version 1.

The state record links operation identity and type, run/task identity, provider and execution phase, attempt/recovery counts, prompt/response SHA-256 digests, verification state, commit/PR lineage, normalized failure signature, and lifecycle timestamps.

Full prompts and responses are deliberately excluded from the canonical record. Existing queue/terminal-response storage remains responsible for bounded payload retention.

## Compatibility boundary

Existing bridge and runner state files may contain richer legacy fields. They can be projected into `OperationState` without requiring an unsafe rewrite of those files. New control-plane consumers should use `OperationState` as the shared lineage envelope and keep provider/browser-specific details outside the contract.

Schema changes must increment `schema_version` and add explicit migration logic. Unknown or unsupported versions must fail closed rather than being guessed.
