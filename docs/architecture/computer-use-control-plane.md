# Computer-Use Control Plane

The Computer-Use Control Plane (CUCP) is the provider-independent boundary between PASI orchestration and external AI, development, repository, research, and desktop interfaces.

## Design goal

The CUCP enables PASI to operate tools in a human-like workflow without putting UI automation or provider-specific behavior into the core orchestrator. The implementation is contract-first: it defines sessions, semantic actions, observations, AI responses, completion states, context packages, events, and replaceable adapters. Concrete automation is added only behind these contracts.

## Control loop

```text
Observe
  ↓
Plan
  ↓
Authorize
  ↓
Execute
  ↓
Observe
  ↓
Verify
  ↓
Continue / Complete / Pause / Fail
```

The controller is a deterministic state machine. It does not execute arbitrary desktop or shell actions itself.

## Provider boundaries

```text
AIAdapter
  ├── ChatGPT
  ├── Claude
  ├── OpenRouter
  └── future local/specialized models

ComputerAdapter
  ├── desktop
  ├── browser
  └── future isolated sessions

IDEAdapter
  └── VS Code / language-server diagnostics / bounded evidence

GitHubAdapter
  ├── GitHub connector/API
  └── GitHub UI automation when an API operation is insufficient

ResearchAdapter
  └── web search + source retrieval
```

Core contracts must not contain provider-specific selectors, coordinates, DOM structure, or browser implementation details.

## VS Code observation and diagnostics

`VSCodeEvidenceAdapter` is the first concrete IDE implementation. It is intentionally read-only and can be used without driving the VS Code UI directly. It provides four semantic operations through the `IDEAdapter` contract:

- workspace observation, including a bounded file inventory and optional editor-state snapshot;
- workspace-relative file reads with a configurable byte limit;
- case-insensitive bounded text search over non-generated workspace files;
- normalized diagnostics loaded from a structured JSON snapshot produced by VS Code/LSP tooling.

Diagnostics are normalized into stable fields for path, position, severity, source, message, range, and code. They are sorted deterministically and carry a content fingerprint so the same evidence can be compared across observations.

State and diagnostics snapshots are evidence inputs, not execution instructions. Paths must resolve inside the workspace root, absolute paths are rejected, common generated/environment directories are skipped during inventory/search, and no write/delete/command API exists on the adapter.

The adapter therefore fits the future context loop as:

```text
VS Code / LSP evidence
  ↓
VSCodeEvidenceAdapter
  ↓
Observation (workspace / file / search / diagnostics)
  ↓
ContextCollector
  ↓
ContextPackage
  ↓
AI provider / conditional follow-up
```

A later VS Code integration can publish the same state/diagnostics schema from an extension or accessibility/API layer without changing the core CUCP contracts.

## ChatGPT adapter and completion detection

`ChatGPTAdapter` is a semantic provider adapter over the existing localhost bridge at `127.0.0.1:8765`. It does not duplicate ChatGPT browser transport or embed DOM selectors in Python. The Tampermonkey controller remains the component that interacts with ChatGPT's page.

The adapter exposes:

- `new_session()`, which queues a verified `new_chat` operation and waits for the controller's completion acknowledgement;
- `submit_prompt(prompt)`, which queues a semantic prompt operation;
- `read_response()`, which reads normalized operation state through the bridge;
- bounded `wait_for_completion()` polling;
- an explicit failure when reasoning-mode UI control is requested but the current bridge/controller does not expose that capability.

The existing controller now dispatches `new_chat` operations to its verified `startNewChat()` workflow. Prompt operations continue through the existing composer insertion, send-button verification, and generation polling path. The controller reports completion only after it observes generation stop across its verification window.

Completion and response-text capture are deliberately separate. A `complete` state means the provider-side operation finished according to the controller's verified completion path; `response_available` indicates whether assistant text was actually captured. This allows the system to continue orchestration without pretending that missing response text exists.

The normalized completion states are:

`generating`, `quiet`, `complete`, `interrupted`, `error`, `timeout`, and `unknown`.

Unknown or ambiguous evidence never becomes success. A completed operation is still allowed to have `response_available = false`, while a response marked available must contain non-empty text. This distinction is important for later conditional prompting and evidence provenance.

## Context and conditional prompting

A later context engine will collect task-scoped observations from VS Code, GitHub, web research, prior AI responses, tests, and deterministic PASI artifacts. It will produce a `ContextPackage` that can be supplied to an AI provider.

The intended loop is:

```text
AI response
  ↓
Evaluate response against task state
  ↓
Collect missing/independent evidence
  ↓
Compose conditional follow-up prompt
  ↓
Submit to selected provider
```

The follow-up prompt is therefore evidence-driven rather than a fixed retry string.

## Authorization

Computer-use actions must pass through PASI authorization before execution. Safe read/observation actions can proceed without external approval. Actions that modify workspaces, operate consequential GitHub controls, or control the desktop require the appropriate policy permission and external human approval. Unknown actions fail closed.

GUI automation must never bypass authorization simply because a button is visible.

## Background operation

Background operation is modeled on the `Session` boundary. A session identifies the task, project, permitted applications, workspace root, duration limit, and whether it is intended to run in the background.

A production worker should prefer isolated browser/application sessions and semantic/accessibility/API interfaces over raw mouse coordinates. The user must be able to pause, resume, stop, inspect, and recover a session.

Background operation does not imply unrestricted access to the user's computer. Credentials, password managers, banking/brokerage systems, arbitrary privileged administration, and unrelated personal data remain outside the capability boundary.

## Events and provenance

Control-plane events are structured records linking observations, actions, authorization decisions, AI responses, and verification. This enables debugging and future replay/audit workflows:

```text
Task
 ↓
Context
 ↓
Prompt
 ↓
AI response
 ↓
Action
 ↓
Result
 ↓
Verification
```

## Implementation sequence

1. Contract and state-machine foundation.
2. Read-only VS Code observation and diagnostics adapter.
3. ChatGPT adapter integration with robust completion detection (this slice).
4. Conditional prompt/context engine.
5. Web research adapter.
6. Claude independent-review adapter.
7. GitHub API/connector plus UI fallback adapter.
8. Persistent background worker with pause/resume/recovery.
9. Integration with simulation provenance and verification telemetry.

The system should not skip the contract and authorization layers in order to reach end-to-end UI automation faster; those layers are what make later autonomy replaceable, testable, and governable.
