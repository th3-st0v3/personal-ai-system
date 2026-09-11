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

- item-specific context menus for projects, folders, notes, and files
- multi-selection
- bulk delete and delete-all-files
- rename, copy/move, and drag/drop-style moves
- recursive folder movement with cycle protection
- breadcrumbs
- recursive search/listing hooks
- A-Z, Z-A, recent-to-old, old-to-recent, and both last-modified directions

Context actions deliberately vary by resource type. A folder exposes creation/organization actions, a note exposes editing/export actions, and a file exposes preview/download/replace actions. Multi-selection exposes only actions that make sense for a heterogeneous selection.

## Calculations

Calculations are deterministic Python functions, not AI-generated arithmetic. They are registered by stable keys and carry equation, assumptions, limitations, units, and an auditable calculation trace.

The calculation registry is designed to expand across engineering domains without changing callers. Current coverage includes fluid pressure/flow, geometry, thermodynamics, solid mechanics, electrical power, and mechanical power, with additional models added through the same registry and metadata boundary.

A calculation trace exposes the equation, substituted values, evaluation step, result, units, assumptions, and limitations. This allows a UI to provide concise answers or detailed engineering derivations without duplicating numerical logic.

## Frontend contract

The frontend should treat `WorkspaceApplication` and the browser/calculation application boundaries as the API surface. Storage details, SQLite rows, and physical file paths should not leak into UI components.

The eventual web product can therefore add richer navigation, editor experiences, tabs, panes, command palettes, context menus, keyboard shortcuts, drag/drop, previews, plotting, simulation views, and AI assistance without changing the underlying project model.

## Beta definition of done

A beta foundation is expected to support real workflows end-to-end rather than demonstrate isolated feature stubs. New capabilities should extend stable registries and application boundaries, add tests, and preserve existing behavior where compatibility matters.

Complexity is justified when it buys a durable capability, stronger correctness, extensibility, safety, or a substantial reduction in future rewrites. The goal is not the fewest lines of code; it is the smallest architecture that can credibly carry the intended beta product.
