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
- Safe local storage of file bytes

The database stores **file metadata**, while `src/file_storage.py` owns physical bytes. `storage_key` is the stable boundary between the two. This keeps database identity independent from the local filesystem and preserves a future path to an object store or remote storage implementation.

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
- Storage keys are relative paths and cannot escape the configured storage root.

## Byte storage boundary

`file_storage.py` provides a deliberately small local backend:

- `save_bytes` writes atomically and returns the SHA-256 digest.
- `read_bytes` retrieves the bytes identified by a storage key.
- `exists` checks for a stored object.
- `delete_bytes` removes an object idempotently.
- `verify_sha256` validates stored content against metadata.

The byte-storage module does not know about projects, tags, folders, requirements, wells, or database records. Conversely, workspace metadata does not assume a particular physical storage implementation.

Storage keys are validated against path traversal, absolute paths, and empty path components before resolution. Writes use a temporary file followed by atomic replacement so an interrupted write does not intentionally expose a partially written destination file.

## Why the storage key is separate from the file name

The user-facing name can change without requiring the underlying stored object to move or be renamed. This supports Rename and Move operations in the web UI without coupling database identity to physical storage.

## Lifecycle and cleanup

Metadata deletion and byte deletion remain separate operations. Deleting a database file record removes its database-owned tag assignments and cascades its attachment records, but it does not implicitly delete physical bytes. A future higher-level file service can coordinate metadata and byte cleanup with explicit recovery/error handling rather than hiding filesystem side effects inside database operations.

Empty folders can be deleted; non-empty folders are rejected. Folder tag assignments are removed when an empty folder is deleted. Lifecycle transitions are idempotent and do not recursively mutate children.

## Future frontend mapping

The backend primitives are intended to support the eventual file-explorer UX:

| UI action | Backend primitive |
| --- | --- |
| Open | `get_file` + storage-key retrieval layer |
| Upload | `file_storage.save_bytes` + file metadata creation |
| Rename | `rename_file` / `rename_folder` |
| Move | `move_file` / `move_folder` |
| Tag | `create_tag` / `assign_tag` / `remove_tag` |
| Archive | lifecycle update |
| Invalidate | lifecycle update |
| Restore | lifecycle update back to `Active` |
| Delete | `delete_file` / `delete_files` / `delete_folder` |
| Attach to engineering object | `attach_file` / `detach_file` |

Upload/download streaming, previews, permissions, audit events, and soft-delete recovery remain separate concerns. They should be added behind stable interfaces without changing the core file identity model.
