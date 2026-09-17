# Active Project Behavior

The runner should treat the active project as a continuing engineering session. Full context is established once. Ordinary subsequent prompts should be compact `Continue working...` requests sent to the same valid ChatGPT conversation. The runner should not inject full context repeatedly.

Advance to a new task only after the current task is actually verified, committed, and promoted.

Default continuation: `Continue working on the active Computer-Use Control Plane engineering task. Do not stop at analysis. Continue implementing, testing, verifying, and repairing the work until the current task is actually complete.`