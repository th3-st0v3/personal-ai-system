# Workspace Storage

The workspace storage subsystem provides the backend foundation for the future web file explorer.

## Scope

The current subsystem models:

- Folders with project-scoped hierarchy
- Files with stable storage keys and integrity metadata
- Attachments linking files to supported project-owned engineering objects
- Project-scoped tags and tag assignments
- Lifecycle state for files and folders
- Individual and bulk file deletion
- File and folder moves

The subsystem intentionally stores **file metadata**, not file bytes. `storage_key` identifies the object in the eventual storage layer. This keeps the database independent from the eventual local filesystem, object store, or web upload service.

## Integrity rules

- A folder belongs to exactly one project.
- A child folder must belong to the same project as its parent.
- A file's folder must belong to the same project as the file.
- A file stores a SHA-256 digest and non-negative byte count.
- A tag belongs to exactly one project.
- A tag can only be assigned to a target in the same project.
- An attachment can only link a file to a target in the same project.
- Folder moves reject cycles.
- File/folder lifecycle values are limited to `Active`, `Archived`, `Invalidated`, and `Superseded`.

## Why the storage key is separate from the file name

The user-facing name can change without requiring the underlying stored object to move or be renamed. This supports future Rename and Move operations in the web UI without coupling database identity to physical storage.

## Future frontend mapping

The backend primitives are intended to support the eventual file-explorer UX:

| UI action | Backend primitive |
| --- | --- |
| Open | `get_file` + storage-key retrieval layer |
| Rename | file metadata update to be added |
| Move | `move_file` / `move_folder` |
| Tag | `create_tag` / `assign_tag` / `remove_tag` |
| Archive | lifecycle update |
| Invalidate | lifecycle update |
| Restore | lifecycle update back to `Active` |
| Delete | `delete_file` / `delete_files` |
| Attach to engineering object | `attach_file` / `detach_file` |

Actual byte storage, upload/download streaming, previews, permissions, audit events, and soft-delete recovery remain separate concerns. They should be added without changing the core file identity model.
