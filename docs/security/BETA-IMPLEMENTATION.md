# Beta Security Implementation Notes

This document records how the current browser beta maps the repository security policy to concrete boundaries. The long-term policy remains authoritative in `SECURITY.md`.

## Current enforced boundaries

- The browser server binds to `127.0.0.1` by default and uses port `8000`.
- The HTTP layer enforces request-size ceilings and rejects malformed JSON before application actions run.
- Workspace, engineering requirements, sources, and evidence are validated against the requested project.
- Physical file bytes stay behind the workspace/file-storage application boundary; the browser does not access SQLite or filesystem paths directly.
- PDF ingestion decodes uploaded bytes in a bounded request and passes extracted text through the same project-scoped ingestion policy as other sources.
- Simulation execution passes through the explicit policy service before running.
- External source content is represented as source data and evidence, not trusted application instructions.
- Chat, connections, plugins, and source retrieval are exposed through application/API boundaries rather than arbitrary browser shell access.
- Financial functionality remains information-only; the current browser/API surface contains no brokerage, order, margin, options-execution, or money-transfer capability.

## Required validation for new integrations

Any new agent, connector, plugin, MCP server, package, or external API must preserve least privilege, explicit authorization, project isolation, auditability, and the trust hierarchy defined in `SECURITY.md`.

Adding a UI control is not sufficient evidence that a capability is safely implemented. The application boundary must enforce the same restriction for direct HTTP clients.

## Regression expectation

Changes to security-sensitive boundaries should add or update backend tests, frontend contract checks where applicable, and CI coverage. A stale UI assertion must not be “fixed” by deleting a working feature; the contract should instead be reconciled with the actual supported backend surface.
