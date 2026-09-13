# Beta Workspace and Calculation Architecture

## Direction

The project is no longer planned around a minimal notes/project MVP. The target is a beta-capable technical workspace whose foundations support substantial functionality without requiring repeated rewrites.

## Project model

A project is an isolated workspace boundary. Its name and description identify it, but the project itself owns the user's working environment: folders, notes, uploaded files, engineering entities, evidence, calculations, tags, and future capabilities.

The workspace is an unbounded tree rather than a fixed set of screens. Folders may contain folders, notes, and files at arbitrary depth. The backend must not impose an application-level nesting limit.

Physical file bytes remain separate from database metadata. Existing `workspace_storage` manages file/folder metadata and `file_storage` manages bytes; `workspace_file_service` coordinates the two.

## Browser behavior

The browser contract is UI-agnostic. A frontend can render a tree, sidebar, table, tabs, split view, canvas, or other layout while using the same operations.

Supported workspace semantics include:

- item-specific context menus for folders, notes, and files
- root-level creation actions
- multi-selection
- bulk delete and delete-all-files
- rename, copy/duplicate, move, and drag/drop-style moves
- recursive folder copying with conflict renaming and cycle protection
- project-scoped clipboard validation
- breadcrumbs
- recursive search/listing hooks
- A-Z, Z-A, recent-to-old, old-to-recent, and both last-modified directions

Context actions deliberately vary by resource type. A folder exposes creation/organization actions, a note exposes editing/export actions, and a file exposes preview/download/replace actions. Multi-selection exposes only actions that make sense for a heterogeneous selection.

The current beta web shell keeps those semantics behind the HTTP boundary. It is intentionally usable now while leaving room for richer dialogs, editors, previews, command palettes, and other UX decisions that can be refined later without changing storage contracts.

## Calculations

Calculations are deterministic Python functions, not AI-generated arithmetic. They are registered by stable keys and carry equation, assumptions, limitations, units, and an auditable calculation trace.

The calculation registry is designed to expand across engineering domains without changing callers. Current coverage includes fluid pressure/flow, geometry, thermodynamics, solid mechanics, electrical power, mechanical power, drilling hydraulics, and reservoir-property/productivity calculations, with additional models added through the same registry and metadata boundary.

Calculation parameter metadata is derived from executable function signatures for required-vs-defaulted inputs. This prevents the UI from requiring values that the calculation engine can safely supply itself.

A calculation trace exposes the equation, substituted values, evaluation step, result, units, assumptions, and limitations. This allows a UI to provide concise answers or detailed engineering derivations without duplicating numerical logic.

## HTTP and safety boundaries

The web API is a replaceable JSON boundary over the application services. Resource identifiers are validated against the requested project, workspace item kinds are explicitly constrained, malformed request bodies are rejected, and request bodies have a fixed size ceiling. The WSGI adapter also rejects oversized declared content lengths before reading the body.

These checks are part of the beta foundation rather than frontend-only behavior so alternative clients cannot bypass project isolation or resource validation.

## Frontend contract

The frontend should treat `WorkspaceApplication` and the browser/calculation application boundaries as the API surface. Storage details, SQLite rows, and physical file paths should not leak into UI components.

The current shell supports project selection, workspace navigation, breadcrumbs, sorting, recursive project search, contextual actions, keyboard item navigation, drag/drop moves, copy/paste/duplicate, root creation actions, and deterministic calculation forms/traces. The eventual web product can add richer editors, tabs, panes, command palettes, previews, plotting, simulation views, and AI assistance without changing the underlying project model.

## Beta definition of done

A beta foundation is expected to support real workflows end-to-end rather than demonstrate isolated feature stubs. New capabilities should extend stable registries and application boundaries, add tests, and preserve existing behavior where compatibility matters.

The draft beta is considered technically viable when the backend/application/API contracts are coherent, cross-project isolation is enforced, deterministic calculations are traceable, file metadata and bytes remain separated, the web shell can exercise the major workspace/calculation workflows, and CI prevents regressions without unbounded test execution.

Complexity is justified when it buys a durable capability, stronger correctness, extensibility, safety, or a substantial reduction in future rewrites. The goal is not the fewest lines of code; it is the smallest architecture that can credibly carry the intended beta product.
