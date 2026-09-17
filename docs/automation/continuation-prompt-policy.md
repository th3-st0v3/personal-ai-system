# Conditional Context and Continuation Prompt Policy

PASI should distinguish between an **initial task prompt**, a **normal continuation prompt**, a **recovery prompt**, and a **new-project prompt**.

## Initial task prompt
Send the substantive project/task context, acceptance criteria, and the minimum required repository/runtime context when establishing a new active conversation or when continuity cannot be trusted.

## Normal continuation prompt
When the existing ChatGPT conversation is still usable and the previous task turn completed successfully, do not resend the full project context. Send only a compact continuation instruction, for example:

`Continue working on the active Computer-Use Control Plane engineering task. Do not stop at analysis. Continue implementing, testing, verifying, and repairing the work until the current task is actually complete.`

The conversation history is the primary task context. Persistent project memory remains available as a recovery/context source, not something to paste into every turn.

## Recovery prompt
Only reconstruct enough context to recover safely after context loss, new conversation creation, provider rollover, or an unreliable/stale session. Prefer persisted task state and project memory over copying entire prior model responses.

## New project prompt
When a project in the user task queue becomes active, provide its substantive brief once, then use normal continuation prompts for subsequent work on that same project until its acceptance criteria are met.

## Conditional context triggers
Fuller context may be injected only when:
- a new ChatGPT conversation is created;
- the current conversation is exhausted;
- state continuity is stale/untrusted;
- the active project changes materially;
- a required repository/runtime fact is missing;
- or recovery requires explicit reconstruction.

## Completion behavior
Do not use continuation prompts as a way to declare a task complete. The active task remains active until verified acceptance criteria are met. After verified completion, commit/promote the meaningful increment and only then start the next task.

## Anti-loop behavior
The continuation prompt must tell the model to keep making substantive progress, not merely restate the plan or answer semantically. Repeated turns must result in implementation, testing, debugging, verification, or another concrete engineering action whenever work remains.

## Safety
Continuation does not expand permissions. Existing approval, authorization, path, network, authentication, human-control, and verification boundaries apply identically to initial and continuation prompts.
