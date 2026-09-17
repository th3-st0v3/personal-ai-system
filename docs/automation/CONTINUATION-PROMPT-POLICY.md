# Conditional Context and Continuation Prompt Policy

PASI should distinguish between an initial task prompt, a normal continuation prompt, a recovery prompt, and a new-project prompt.

## Initial task prompt
Send the substantive project/task context, acceptance criteria, and the minimum required repository/runtime context when establishing a new active conversation or when continuity cannot be trusted.

## Normal continuation prompt
When the existing ChatGPT conversation is still usable and work remains, do not resend the full project context. Send only a compact continuation instruction:

`Continue working on the active Computer-Use Control Plane engineering task. Do not stop at analysis. Continue implementing, testing, verifying, and repairing the work until the current task is actually complete.`

The conversation history is the primary task context. Persistent project memory is a recovery/context source, not something to paste into every turn.

## Conditional context triggers
Inject fuller context only when a new conversation is created, the current conversation is exhausted, state continuity is stale or untrusted, the active project changes materially, a required fact is missing, or recovery requires reconstruction.

## Completion behavior
Do not use a continuation prompt to declare completion. Keep the active task until verified acceptance criteria are met. Then commit/promote and start the next substantial task.

## Anti-loop behavior
Each continuation must drive concrete implementation, testing, debugging, verification, or another engineering action when work remains. Do not merely restate a plan.

## Safety
Continuation does not expand permissions. Existing approval, authorization, authentication, path, network, human-control, and verification boundaries remain mandatory.