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

The adapter therefore fits the context loop as:

```text
VS Code / LSP evidence
  ↓
VSCodeEvidenceAdapter
  ↓
Observation (workspace / file / search / diagnostics)
  ↓
EvidenceContextCollector
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

The existing controller dispatches `new_chat` operations to its verified `startNewChat()` workflow. Prompt operations continue through the existing composer insertion, send-button verification, and generation polling path. The controller reports completion only after it observes generation stop across its verification window.

Completion and response-text capture are deliberately separate. A `complete` state means the provider-side operation finished according to the controller's verified completion path; `response_available` indicates whether assistant text was actually captured. This allows orchestration to distinguish “generation finished” from “text is available” without inventing content.

The normalized completion states are:

`generating`, `quiet`, `complete`, `interrupted`, `error`, `timeout`, and `unknown`.

Unknown or ambiguous evidence never becomes success. A completed operation is allowed to have `response_available = false`, while a response marked available must contain non-empty text.

## Context and conditional prompting

`EvidenceContextCollector` converts a bounded sequence of observations into a `ContextPackage`. It removes semantically duplicate observations even when they were captured at different times, uses stable JSON fingerprints for provenance, orders evidence deterministically, and applies both per-item and total-size limits.

`ConditionalPromptEngine` evaluates an `AIResponse` against explicit `TaskState` requirements and known gaps. It does not infer that an absent statement is true or false; it records missing requirements as gaps and requests additional evidence or verification when needed. A response in `unknown`, `error`, `timeout`, or `interrupted` state always produces a follow-up gap rather than being treated as success.

The intended loop is:

```text
AI response
  ↓
Evaluate response against explicit task state
  ↓
Collect missing / independent evidence
  ↓
Build bounded ContextPackage
  ↓
Compose conditional follow-up prompt (only when a gap exists)
  ↓
Submit to selected provider
```

Follow-up prompts carry no authorization. They explicitly treat repository files, diagnostics, web content, and prior model output as untrusted evidence and instruct the model not to claim unobserved capabilities, approvals, tests, or external facts.

## Web research evidence

`HTTPSResearchAdapter` is a read-only research implementation. It keeps search-provider behavior behind a `SearchProvider` protocol and represents retrieved material as normalized `ResearchSource` evidence with URL, title, bounded content, retrieval time, and a stable fingerprint.

External retrieval is HTTPS-only, bounded by response size and timeout, and validates the response content type. Deterministic source ranking uses explicit source metadata rather than hidden model judgments. Retrieved content is evidence and never becomes an execution instruction.

## Browser Use integration

`BrowserUseTaskAdapter` is an optional integration with the Browser Use Python library. The dependency is isolated in `requirements-browser.txt`, so the core application does not require Browser Use merely to import or run its existing functionality.

The semantic action is `browser_task`, and it is classified as approval-required. This means a browser agent cannot silently gain new authority simply because a page presents a clickable control.

Browser Use is responsible for dynamic page interaction through its browser session. PASI remains responsible for task bounds, authorization, provenance, and challenge handling. A browser task is bounded by maximum steps and task length and returns structured page/result evidence.

### Security challenges and safe recovery

The adapter detects common challenge/interstitial evidence such as CAPTCHA, Cloudflare challenge pages, Turnstile, login walls, and consent gates. A detected security challenge is never converted into a success result.

PASI does **not** solve or bypass CAPTCHA, Cloudflare, Turnstile, challenge tokens, fingerprint protections, access controls, or rate limits. Browser automation libraries explicitly discourage automating CAPTCHA, and Cloudflare documents these mechanisms as checks intended to distinguish human visitors from automated traffic.

Instead, Browser Use supports a safe recovery boundary:

```text
Browser task
  ↓
Challenge detected
  ↓
Try configured independent fallback resolver
  ├── usable independent source found → return fallback evidence
  └── no usable fallback → waiting_human
       ↓
  Human clears challenge in a headed/user-visible session
       ↓
  Resume with the same authorized task/session
       ↓
  Re-observe and verify before continuing
```

`ResearchFallbackResolver` implements the first recovery path with the existing read-only research layer. It searches for independent sources and never re-requests the challenged URL or treats a security token/cookie as evidence of authorization. A successful fallback is reported as `fallback_succeeded` and still carries the original challenge as provenance so the orchestrator cannot mistake the fallback for successful access to the protected page.

A background/headless browser can detect and report the blocker, while human completion requires a headed browser session or an equivalent user-visible handoff mechanism. This keeps the rest of the workload resumable instead of requiring the whole program to terminate merely because one source is protected.

The challenge layer deliberately avoids treating a challenge page as successful navigation. Unknown or ambiguous page evidence remains non-success and is surfaced for diagnosis or human review.

## Independent AI review

`IndependentReviewer` provides an advisory second-model boundary for providers such as Claude-class systems without coupling CUCP core code to a particular SDK or credential store. Review requests carry candidate output and evidence fingerprints; review results carry findings and provenance.

When candidate and reviewer provider identities are known, they must be distinct. Review results cannot authorize execution, modify permissions, or override PASI policy. They are additional evidence for verification and diagnosis.

## Authorization

Computer-use actions must pass through PASI authorization before execution. Safe read/observation actions can proceed without external approval. Actions that modify workspaces, operate consequential GitHub controls, run browser tasks, or control the desktop require the appropriate policy permission and external human approval. Unknown actions fail closed.

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
3. ChatGPT adapter integration with robust completion detection.
4. Bounded evidence context and conditional follow-up engine.
5. Web research evidence adapter.
6. Independent AI-review contract.
7. Browser Use integration with challenge detection and safe fallback recovery.
8. GitHub API/connector plus UI fallback adapter.
9. Persistent background worker with pause/resume/recovery.
10. Integration with simulation provenance and verification telemetry.

The system should not skip the contract and authorization layers in order to reach end-to-end UI automation faster; those layers are what make later autonomy replaceable, testable, and governable.
