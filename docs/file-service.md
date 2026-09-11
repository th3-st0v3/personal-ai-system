# Workspace File Service

`src/workspace_file_service.py` is the application boundary between workspace file metadata and physical byte storage.

## Create flow

1. Validate and materialize the incoming bytes.
2. Generate a stable, filename-independent `storage_key`.
3. Atomically write the bytes through `file_storage`.
4. Create the workspace metadata record with size and SHA-256 digest.
5. If metadata creation fails, remove the newly written bytes before re-raising.

This prevents a normal failed upload from leaving metadata that points at a missing object or a newly orphaned byte object.

## Delete flow

Deletion removes workspace metadata first, then attempts physical byte cleanup. This deliberately prefers a recoverable orphaned byte object over a metadata record that points at missing bytes.

If physical cleanup fails after metadata deletion, the service raises `FileServiceError` so the caller knows that cleanup is required. The physical object remains available for recovery/cleanup rather than being silently lost.

## Boundary responsibilities

- `workspace_storage` owns metadata, lifecycle, tags, and attachments.
- `file_storage` owns physical bytes and storage-key safety.
- `workspace_file_service` coordinates the two without moving filesystem logic into the database layer.

The service accepts a storage root rather than depending on a global path, keeping future API/server deployment and alternate storage backends straightforward.
