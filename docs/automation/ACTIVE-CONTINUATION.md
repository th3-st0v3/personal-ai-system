# Active Continuation Mode

The unattended runner should treat the current engineering objective as active across multiple prompts. A new prompt is not a new project context injection.

Normal turn: `Continue working on the active Computer-Use Control Plane engineering task. Do not stop at analysis. Continue implementing, testing, verifying, and repairing the work until the current task is actually complete.`

Context injection is conditional: only on new conversation, context exhaustion/loss, material project change, missing required state, or recovery.

Advance to the next large task only after the current one is verified and promoted through the normal Git workflow.