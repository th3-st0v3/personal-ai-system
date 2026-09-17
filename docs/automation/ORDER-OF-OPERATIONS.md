# PASI Large Engineering Order of Operations

The runner should complete one substantial engineering objective at a time. The active ChatGPT conversation carries context across continuation turns; the full brief is not repeated on every prompt.

1. Establish the active objective and acceptance criteria once.
2. Reuse the same ChatGPT conversation while it remains valid.
3. Send compact continuation prompts while the current objective still has unfinished work.
4. Inspect architecture and runtime state.
5. Implement meaningful code/configuration changes.
6. Operate the relevant controlled computer surfaces when needed: WSL/terminal, VS Code, browser, ChatGPT, Tampermonkey, GitHub, and research.
7. Test the implementation and integration.
8. Diagnose failures.
9. Repair and retest until verified.
10. Commit the meaningful increment.
11. Push and use the existing risk-gated promotion/merge path.
12. Only after verified completion, select the next substantial task from the queue.

## Default queue

1. Computer-Use Control Plane
2. Unattended Task Execution
3. Verification + Self-Repair
4. Persistent Project Memory
5. Multi-AI Orchestration
6. Developer Tool Integration
7. Research + Evidence System
8. Higher-Level Personal AI System
9. Task-Specific/User-Created Models
10. Engineering Knowledge/Learning Layer

## Continuation prompt

Continue working on the active Computer-Use Control Plane engineering task. Do not stop at analysis. Continue implementing, testing, verifying, and repairing the work until the current task is actually complete.

## Conditional context

Full context is reintroduced only when the same conversation cannot reliably carry the required context (new conversation, exhaustion, continuity failure, material project change, missing required state, or recovery).