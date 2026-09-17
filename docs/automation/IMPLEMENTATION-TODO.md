# Automation Implementation TODO

## Highest priority
Implement conditional context and continuation prompting in the active unattended ChatGPT loop.

### Behavior
1. Establish the project context once when starting a new project/conversation.
2. Reuse the same valid ChatGPT conversation for ordinary continuation turns.
3. For ordinary continuation, send only: `Continue working on the active Computer-Use Control Plane engineering task. Do not stop at analysis. Continue implementing, testing, verifying, and repairing the work until the current task is actually complete.`
4. Keep using continuation prompts until the active task's acceptance criteria are actually verified.
5. Only after verification should PASI commit/promote and choose the next large task.
6. Reintroduce full context only after new conversation creation, context exhaustion/loss, material project change, missing required state, or recovery.
7. Add deterministic tests that prove full context is absent from ordinary continuation turns and present when required for recovery/new work.

## Next priority
Build a live queue/inbox for substantial user projects so projects can be added while the runner is active without restarting the process.

## Next after that
Make VS Code, terminal/process control, browser interaction, and Tampermonkey editing/visual verification first-class controlled computer-use surfaces.

## Constraints
Do not weaken approval, authorization, authentication, network, path, human-control, or verification boundaries. Do not manufacture trivial commits to chase contribution counts.