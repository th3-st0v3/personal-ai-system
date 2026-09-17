# Large Engineering Task Queue

## Ordered default roadmap

1. Computer-Use Control Plane — reliable browser/computer interaction, ChatGPT control, VS Code, terminal/process awareness, GitHub, research, state synchronization, response/completion detection, recovery, and persistent operation state.
2. Unattended Task Execution — large objectives, decomposition, continuous execution, completion detection, resume/recovery, and bounded human escalation.
3. Verification + Self-Repair — tests, diagnostics, correction, retest, evidence, and regression prevention.
4. Persistent Project Memory — architecture, requirements, decisions, current work, failures, limitations, and completed milestones.
5. Multi-AI Orchestration — ChatGPT, Claude, specialized models, routing, and context transfer.
6. Developer Tool Integration — GitHub, VS Code, terminal, filesystem, testing, and controlled computer interaction.
7. Research + Evidence System — web research, documentation, source provenance, GitHub research, and engineering evidence.
8. Higher-Level Personal AI System — build the broader product on top of the control plane.
9. Task-Specific/User-Created Models — introduce smaller specialized models where they improve cost or performance.
10. Engineering Knowledge/Learning Layer — connect engineering, programming, mathematics, research, and learning tools.

## Execution rule
Work on one substantial task at a time. Establish project context once, then use compact continuation prompts in the same valid ChatGPT conversation while work remains. Re-inject fuller context only for a new conversation, context loss, material project change, missing required facts, or recovery.

## Continuation prompt
Continue working on the active Computer-Use Control Plane engineering task. Do not stop at analysis. Continue implementing, testing, verifying, and repairing the work until the current task is actually complete.

## Progression rule
Do not advance to the next task until the current task is actually verified. After verification, commit the meaningful increment, promote it through the existing risk-gated flow, and then begin the next substantial task.

## Throughput rule
Maximize useful verified engineering output. Do not manufacture trivial commits or edits simply to reach a numeric contribution target.

## Safety
All authentication, authorization, approval, human-control, path, network, and verification boundaries remain mandatory.