"""Application service coordinating workspace file metadata and bytes.

The workspace metadata layer and physical byte storage layer stay separate.
This module is the orchestration boundary between them.
"""

import uuid

import file_storage
import workspace_storage


class FileServiceError(RuntimeError):
    """Raised when file orchestration cannot complete safely."""


def _storage_key():
    """Generate a stable, filename-independent storage key."""
    return f"files/{uuid.uuid4().hex}"


def create_file(storage_root, project_id, name, data, mime_type=None, folder_id=None):
    """Store bytes and create their workspace metadata record.

    Bytes are written first so the metadata never points at an object that was
    not successfully stored. If metadata creation fails, the newly written
    bytes are removed before the original error is re-raised.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data must be bytes-like.")
    payload = bytes(data)
    storage_key = _storage_key()
    digest = file_storage.save_bytes(storage_root, storage_key, payload)
    try:
        file_id = workspace_storage.create_file(
            project_id=project_id,
            name=name,
            storage_key=storage_key,
            size_bytes=len(payload),
            sha256=digest,
            mime_type=mime_type,
            folder_id=folder_id,
        )
    except Exception:
        try:
            file_storage.delete_bytes(storage_root, storage_key)
        except Exception as cleanup_error:
            raise FileServiceError(
                "File metadata creation failed and the newly stored bytes "
                "could not be cleaned up."
            ) from cleanup_error
        raise
    return file_id


def delete_file(storage_root, file_id):
    """Delete metadata, then physical bytes, with explicit cleanup status.

    Metadata is removed first so a failed physical cleanup cannot leave a
    normal file record pointing at missing bytes. If physical cleanup fails,
    ``FileServiceError`` identifies that an orphaned object requires cleanup.
    """
    record = workspace_storage.get_file(file_id)
    if record is None:
        raise ValueError(f"No file found with ID {file_id}.")

    storage_key = record[4]
    workspace_storage.delete_file(file_id)
    try:
        deleted = file_storage.delete_bytes(storage_root, storage_key)
    except Exception as exc:
        raise FileServiceError(
            "File metadata was deleted, but physical byte cleanup failed; "
            "the storage object requires cleanup."
        ) from exc
    return deleted
