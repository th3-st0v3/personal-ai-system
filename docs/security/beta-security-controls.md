# Beta security controls

This document records the controls implemented in the beta foundation. It is a product engineering checklist, not a claim of production certification.

## AI and agent boundaries

- Tool execution is allowlisted. The beta AI layer can invoke only registered calculation, simulation, and project-context tools.
- Tool arguments must be structured objects and are validated before dispatch.
- Project and tool output are wrapped as untrusted data before being returned to a frontier model.
- Model context is bounded to prevent uncontrolled prompt growth and accidental resource exhaustion.
- The current beta has no shell, operating-system, deployment, brokerage, credential-management, or production-write AI tool.
- Deterministic engineering calculations and simulations remain independent from the frontier-model provider.

## Authentication and data boundaries

- Login is optional for local use.
- Passwords are stored with salted PBKDF2-HMAC-SHA256 verifiers rather than plaintext.
- Authentication is isolated behind an application service and HTTP boundary.
- Legacy engineering/user schema is migrated into the shared user record instead of creating competing identity tables.
- Workspace operations enforce project ownership at the application boundary and relevant HTTP routes.

## Web and workspace protections

- Request bodies have explicit size limits.
- File paths are constrained to storage-relative keys.
- Cross-project item access is rejected.
- Folder moves prevent cycles.
- Static-file traversal is rejected.
- User-facing file metadata does not expose the internal content digest.
- Errors are surfaced through a bounded notification layer and duplicate inline errors are suppressed.

## Remaining security work before production

- Replace process-local sessions with persistent, revocable sessions and CSRF protection.
- Add rate limiting, account recovery, email verification, and stronger password policy.
- Add encrypted secret storage and provider-specific permission scopes.
- Add a real sandbox for generated code execution; do not execute model-generated code in the application process.
- Add RBAC/ABAC for agents, users, plugins, projects, and external connections.
- Add supply-chain verification, dependency scanning, SAST/DAST, and security regression/fuzz tests to CI.
- Add durable audit logs for model requests, tool calls, approvals, and autonomous actions.
- Add vector/RAG isolation, provenance, and poisoning defenses when repository-wide memory is introduced.
- Add a human approval gate before any future write, deployment, financial, credential, or external-system action.

## Reference frameworks

The beta aligns its design direction with the OWASP GenAI/LLM risk categories, OWASP web application verification guidance, and NIST AI risk-management practices. Those references are used as engineering inputs; they do not by themselves make the software compliant with a regulation or certified standard.
