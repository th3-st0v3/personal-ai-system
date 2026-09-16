# Computer-Use Control Plane

The Computer-Use Control Plane (CUCP) is the provider-independent boundary between PASI orchestration and external AI, development, repository, research, and desktop interfaces.

## Design goal

The CUCP enables PASI to operate tools in a human-like workflow without putting UI automation or provider-specific behavior into the core orchestrator. The initial implementation is contract-first: it defines sessions, semantic actions, observations, AI responses, completion states, context packages, events, and replaceable adapters. Concrete automation is added only behind these contracts.

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
  └── VS Code / language-server diagnostics / bounded terminal

GitHubAdapter
  ├── GitHub connector/API
  └── GitHub UI automation when an API operation is insufficient

ResearchAdapter
  └── web search + source retrieval
```

Core contracts must not contain provider-specific selectors, coordinates, DOM structure, or browser implementation details.

## ChatGPT workflow

The existing localhost ChatGPT bridge and Tampermonkey controller remain compatible with this boundary. Future provider integration can expose semantic operations such as:

- `new_session`
- `select_reasoning_mode`
- `submit_prompt`
- `read_response`

Response completion is represented explicitly with `generating`, `quiet`, `complete`, `interrupted`, `error`, `timeout`, and `unknown`. The `unknown` state is intentionally non-success: uncertainty must not be interpreted as completion.

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

1. Contract and state-machine foundation (this slice).
2. Read-only VS Code observation and diagnostics adapter.
3. ChatGPT adapter integration with robust completion detection.
4. Conditional prompt/context engine.
5. Web research adapter.
6. Claude independent-review adapter.
7. GitHub API/connector plus UI fallback adapter.
8. Persistent background worker with pause/resume/recovery.
9. Integration with simulation provenance and verification telemetry.

The system should not skip the contract and authorization layers in order to reach end-to-end UI automation faster; those layers are what make later autonomy replaceable, testable, and governable.
