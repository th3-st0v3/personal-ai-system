# Beta Product Architecture

## Product target

The target is a usable beta engineering workspace, not a minimal CRUD MVP.
The beta should feel like a real web application: projects are isolated workspaces, users can organize material freely, and engineering tools live inside the project instead of being disconnected top-level menus.

The design should minimize future replacement by establishing the important contracts before the web frontend is built.

## Project model

A project is a container for an engineering body of work, not just a name and description.

A project may contain, as needed:

- folders
- notes
- files and attachments
- calculations and calculation records
- wells
- design cases
- requirements
- sources and evidence
- decisions
- reviews
- future engineering objects

The project does not impose one rigid workflow. A user can organize information in the structure that fits the work.

Projects remain isolated from one another. Project-scoped objects must carry or derive their project ownership so the API can enforce boundaries.

## Hierarchy

The workspace must support arbitrary nesting where it is meaningful. Notes and folders may be nested to practical database depth rather than an artificial application limit.

A file-system-like interaction is only a UX metaphor. The product is an engineering workspace, not a file explorer.

## Context-sensitive actions

There is no universal action menu.

Actions are determined by the selected entity type and state. Examples:

- Project: Open, Rename, Archive, Restore, Delete, Create Folder, Create Note, Add File, Calculations, Requirements, Evidence, Settings.
- Folder: Open, Rename, Move, Tag, Archive, Restore, Invalidate, Delete, Create Folder, Create Note, Add File.
- Note: Open, Rename, Move, Duplicate, Tag, Archive, Restore, Invalidate, Delete, Create Child Note.
- File: Open, Rename, Move, Download/Preview, Tag, Archive, Restore, Invalidate, Delete.
- Calculation: Open result, Re-run, Duplicate as new case, Link evidence, Archive.
- Requirement: Open, Edit, Evaluate Evidence, Add Evidence, Archive.

The exact menu belongs to the frontend, but the backend must expose enough metadata and lifecycle operations to make these actions safe.

## Selection

The backend supports single-item and multi-item operations. The frontend may expose checkbox selection, shift selection, drag selection, or other familiar web interaction patterns.

Bulk operations must be atomic where practical and must not silently cross project boundaries.

## Sorting

Collections expose explicit ordering options rather than forcing the UI to implement ad-hoc sorting against raw rows:

- name A-Z
- name Z-A
- created recent-old
- created old-recent
- modified new-old
- modified old-new

The same ordering contract can be reused by folders, notes, files, calculations, requirements, and future project resources where the fields exist.

## Navigation

Every nested application surface has a clear return/cancel path. Navigation state is a frontend concern, but application services must return stable entity identifiers and operation results so the frontend can safely preserve or restore context.

A cancelled creation/edit operation must not create an unwanted record merely because the user entered the screen.

## Files and bytes

Workspace metadata and physical byte storage remain separate. The existing workspace file service is the application boundary between them.

The browser must never talk directly to SQLite or the filesystem. The intended path is:

`Browser -> HTTP/API -> application services -> domain/storage services -> SQLite + byte storage`

Local deployment uses the same boundary that a later private or cloud deployment will use.

## Calculations

Calculations are first-class engineering tools, not generic arithmetic utilities.

Every calculation should have:

1. a stable model identity
2. a method version
3. explicit parameters and units
4. validation rules
5. deterministic execution
6. a detailed result/explanation
7. assumptions and limitations
8. a reproducible calculation record
9. optional linkage to requirements/evidence

The UI should show the engineering meaning of the result, not only a number.

## Expansion strategy

New features should extend stable contracts rather than replace earlier implementations.

Prefer a durable 100-line implementation over a 4-line implementation when the additional structure provides real correctness, extensibility, testability, auditability, or safety value. Avoid abstraction that has no concrete benefit.

The beta is built as a coherent system in vertical slices. Each slice should leave the existing behavior intact and add a complete capability rather than creating a disposable prototype.

## AI boundary

AI is not the authority for deterministic engineering results. Future AI features may select tools, propose scenarios, explain results, compare alternatives, and help navigate project information. Deterministic calculation implementations and stored calculation records remain the source of truth.
