# PASI Orchestration Lifecycle

The orchestrator uses an explicit lifecycle so persisted state describes what the system is actually doing rather than relying on unrestricted phase strings.

## Task phases

```text
selection
   ↓
precheck
   ↓
research
   ↓
context_ready
   ↓
planning
   ↓
awaiting_approval ───────┐
   ↓                     │
executing                │
   ↓                     │
 testing                 │
   ├──→ browser_verification
   ├──→ completed         │
   └──→ diagnosis ───────┘
            ↓
         replanning
            ↓
         planning
```

Any phase can enter `handoff` or `failed` where the transition contract allows it. `completed`, `failed`, and `handoff` are terminal phases and cannot transition further.

## Supervision boundary

Planning is provider-independent. A planner may propose actions, capabilities, and verification requirements, but the lifecycle does not authorize execution merely because a plan exists.

`awaiting_approval` represents an explicit human-control boundary for actions that require approval. Execution belongs after that boundary and should remain subject to the execution policy and audit controls.

## State consistency

A lifecycle transition updates both `CurrentTask` and `ProjectState` together and records the same timestamp. This prevents the task record and project-wide state from silently describing different phases.

The transition graph is intentionally centralized in `automation/orchestrator/orchestration_state.py`. New phases should be added to `automation/orchestrator/orchestration_types.py` and the transition graph/tests before they are used by orchestration code.
