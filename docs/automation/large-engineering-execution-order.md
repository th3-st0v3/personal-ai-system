# Large Engineering Execution Order

PASI should use this order for substantial engineering projects. The order is a default workflow, not a requirement to perform every step when a step is irrelevant.

## 1. Establish the project once

Load the user's project brief and persistent project memory only when required. Establish the active objective, acceptance criteria, constraints, and relevant repository/runtime state.

Do not paste the entire project context into every ChatGPT prompt when the same conversation/session is still valid.

## 2. Continue the existing work session

After the initial project prompt, use the same ChatGPT conversation whenever it remains usable. For ordinary continuation, send a compact instruction such as:

`Continue working on the active Computer-Use Control Plane engineering task. Do not stop at analysis. Continue implementing, testing, verifying, and repairing the work until the current task is actually complete.`

The continuation prompt must rely on the existing conversation context rather than repeating the complete project brief.

Only re-inject fuller context when:
- a new ChatGPT conversation is created;
- the previous conversation is exhausted or context continuity is no longer trustworthy;
- the active project/task changes materially;
- recovery requires explicit state reconstruction;
- or the model explicitly needs missing context that cannot safely be recovered from the current session/project memory.

## 3. Understand architecture and runtime

Inspect the relevant source, interfaces, current runtime state, tests, and existing behavior before editing.

## 4. Implement a substantial increment

Make meaningful source changes that advance the active engineering objective. Avoid replacing engineering work with read-only inspection, cosmetic edits, or documentation-only changes unless documentation is itself the objective.

## 5. Operate required development surfaces

Use the available controlled computer-use surfaces when relevant: terminal/WSL, VS Code, browser, ChatGPT, Tampermonkey, GitHub, and web research. Observe actual results rather than assuming an action succeeded.

## 6. Verify

Run deterministic tests and applicable integration/runtime checks. Collect concrete evidence. Do not claim success from model assertions alone.

## 7. Repair and continue

When verification fails, diagnose the failure, implement a bounded correction, and retest. Do not abandon the active objective merely because one approach failed.

## 8. Complete the current engineering task

Only advance to another task after the current task's acceptance criteria are actually satisfied and the result is verified.

## 9. Commit and promote

Create a meaningful commit, push the branch, and use the existing risk-gated promotion flow. Standard-risk verified changes may request auto-merge after required checks. High-risk controller, browser, security-boundary, provider-routing, and workflow changes remain subject to human review.

## 10. Select the next substantial task

Choose the next highest-value task from the active project roadmap or task queue. Prefer tasks that unlock future capabilities and reduce repeated human intervention.

## Throughput principle

PASI should maximize useful verified engineering throughput, not raw GitHub contribution counts. Do not split trivial work into artificial commits or edits to chase a numeric contribution target. A large project may contain many internal actions, iterations, tests, and commits, but each completed increment must remain meaningful and verifiable.

## Primary initial roadmap

1. Computer-Use Control Plane
2. Unattended Task Execution
3. Verification + Self-Repair
4. Persistent Project Memory
5. Multi-AI Orchestration
6. Developer Tool Integration
7. Research + Evidence System
8. Higher-Level Personal AI System
9. Task-Specific / User-Created Models
10. Engineering Knowledge and Learning Layer
11. Finance information monitoring/analysis with human decisions and execution

All existing authentication, authorization, path, network, approval, human-control, and verification boundaries remain mandatory.