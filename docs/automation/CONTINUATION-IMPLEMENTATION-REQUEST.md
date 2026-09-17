# Continuation Prompt Implementation Request

Implement the conditional-context continuation behavior in the active PASI automation runtime.

## Required behavior

- Initial project/task turn: inject substantive task brief and only the minimum required repository/runtime context.
- Same active ChatGPT conversation with valid continuity: subsequent turns use a compact continuation prompt rather than reposting the full brief, repository description, safety prose, or prior response.
- Example continuation prompt: `Continue working on the active Computer-Use Control Plane engineering task. Do not stop at analysis. Continue implementing, testing, verifying, and repairing the work until the current task is actually complete.`
- Continue prompting the same active task until its verified acceptance criteria are satisfied.
- Only then commit/promote the meaningful increment and move to the next substantial task in the ordered engineering queue.
- Reinject fuller context only for a new conversation, exhausted/lost context, material project change, missing required state, or recovery that requires reconstruction.
- Preserve all existing security, approval, authorization, human-control, network, path, and verification boundaries.

## Quality requirement

Do not merely change prompt wording. Verify that the runner actually reuses the existing ChatGPT conversation and that normal continuation turns no longer duplicate the full context unnecessarily. Add deterministic tests for initial versus continuation/recovery behavior.