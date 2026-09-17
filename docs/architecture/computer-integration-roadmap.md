# PASI Computer Integration Roadmap

PASI should become increasingly useful on the host computer without making the AI provider equivalent to an unrestricted local user.

## Current layer

The system now has three read-only integration surfaces:

1. **ChatGPT browser control** through the native Chromium Manifest V3 controller, with Tampermonkey as a transition fallback.
2. **Workspace access** through named, bounded local capabilities for system metadata, directory listing, UTF-8 file reads, and text search.
3. **VS Code awareness** through an optional dependency-free read-only extension that publishes active editor, workspace, and diagnostic metadata.

The AI can request safe evidence through the PASI computer capability protocol. PASI executes the request and feeds the result back into the same conversation.

## Expansion order

### A. Observe more

Add safe observation capabilities before adding interaction:

- workspace search/index hints,
- tool availability and versions without exposing environment variables,
- bounded resource telemetry,
- provider/browser health,
- IDE diagnostics and project state,
- narrow process metadata when a concrete recovery use case exists.

Observation capabilities should not expose credentials, process arguments, environment variables, clipboard contents, or arbitrary screen contents by default.

### B. Interact with specific applications

Build dedicated adapters for applications that PASI actually needs, such as VS Code and Chromium. Each adapter should expose a small semantic API instead of generic desktop input.

Examples:

- inspect an IDE workspace,
- request a diagnostic refresh,
- navigate a controlled browser tab,
- collect a page observation,
- identify a stalled controller.

### C. Make controlled changes

Writes and commands belong behind the existing execution authorization boundary. A future capability may be available only when:

- the capability is named and allowlisted,
- the target path/application is scoped,
- parameters are validated,
- the request has the required human approval,
- the action is logged,
- the result is verified independently where practical,
- interruption/retry behavior is deterministic.

The model must never turn an approval-required capability into an implicit safe capability by wording its request differently.

### D. Optional native OS integration

Where browser or IDE extensions become limiting, introduce a small native helper using an OS-specific transport such as native messaging. The helper should still call PASI's capability gateway rather than exposing a general-purpose shell.

Optional permissions should be used for capabilities that are not required for normal operation so users can enable them deliberately.

### E. Consequential boundary

These remain outside unattended computer integration:

- credential/secret extraction,
- password-manager contents,
- arbitrary financial execution,
- brokerage actions,
- destructive system operations,
- unrestricted remote-control capability,
- arbitrary deployment or publication with no approval boundary.

## Dependency-reduction objective

Every new integration should replace or reduce a brittle third-party dependency where practical.

Preferred order:

1. platform/web API or standard library,
2. small first-party adapter,
3. existing provider-neutral PASI interface,
4. third-party automation library only when it materially adds capability that cannot be implemented safely and reliably in the lower layers.

The native Chromium controller demonstrates this approach: it uses standard browser extension APIs instead of Tampermonkey APIs. The VS Code integration follows the same principle with no npm runtime dependencies.
