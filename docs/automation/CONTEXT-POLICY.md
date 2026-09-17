# Conditional Context Policy

The automation should not paste the full project context into every prompt.

Initial turn: provide the substantive project objective, acceptance criteria, and minimum necessary repository/runtime information.

Continuation turn: reuse the same ChatGPT conversation and send a compact continuation instruction. The conversation history is the normal source of context.

Default continuation:

`Continue working on the active Computer-Use Control Plane engineering task. Do not stop at analysis. Continue implementing, testing, verifying, and repairing the work until the current task is actually complete.`

Reconstruct fuller context only on new conversation, exhausted/lost context, material project change, missing required state, or recovery.

Never use continuation to bypass approval or verification boundaries.