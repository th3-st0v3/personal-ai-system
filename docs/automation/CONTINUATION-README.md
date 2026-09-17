# Continuation Prompting

The active task gets full context once. Normal subsequent turns use a compact continuation prompt in the same valid ChatGPT conversation. Full context is reconstructed only when continuity is lost, a new conversation is created, the project changes materially, required state is missing, or recovery requires it.

Default continuation prompt:

`Continue working on the active Computer-Use Control Plane engineering task. Do not stop at analysis. Continue implementing, testing, verifying, and repairing the work until the current task is actually complete.`
