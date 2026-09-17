"""Application service coordinating workspace file metadata and bytes."""

from pathlib import Path
import uuid

import file_storage
import workspace_storage


class FileServiceError(RuntimeError):
    """Raised when file orchestration cannot complete safely."""


# workspace_storage returns this stable column order from _FILE_COLUMNS.
_FILE_STORAGE_KEY_INDEX = 4
_FILE_MIME_TYPE_INDEX = 5


def _storage_key():
    return f"files/{uuid.uuid4().hex}"


def create_file(storage_root, project_id, name, data, mime_type=None, folder_id=None):
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
                "File metadata creation failed and the newly stored bytes could not be cleaned up. "
                "Run reconcile_storage() to find the orphaned object."
            ) from cleanup_error
        raise
    return file_id


def replace_file(storage_root, file_id, data, mime_type=None):
    """Replace bytes while keeping metadata valid across partial failures."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data must be bytes-like.")
    record = workspace_storage.get_file(file_id)
    if record is None:
        raise ValueError(f"No file found with ID {file_id}.")

    payload = bytes(data)
    new_key = _storage_key()
    digest = file_storage.save_bytes(storage_root, new_key, payload)
    old_key = record[_FILE_STORAGE_KEY_INDEX]
    try:
        workspace_storage.replace_file_record(
            file_id,
            new_key,
            len(payload),
            digest,
            mime_type if mime_type is not None else record[_FILE_MIME_TYPE_INDEX],
        )
    except Exception:
        try:
            file_storage.delete_bytes(storage_root, new_key)
        except Exception as cleanup_error:
            raise FileServiceError(
                "File metadata replacement failed and the replacement bytes could not be cleaned up. "
                "Run reconcile_storage() to find the orphaned object."
            ) from cleanup_error
        raise

    try:
        file_storage.delete_bytes(storage_root, old_key)
    except Exception as exc:
        # The metadata already points to a valid new object. Leaving the old
        # object behind is safe; reconcile_storage() can remove it later.
        raise FileServiceError(
            "File metadata now points to the replacement bytes, but the previous byte object could not be cleaned up. "
            "Run reconcile_storage() to remove the orphaned object."
        ) from exc
    return workspace_storage.get_file(file_id)


def delete_file(storage_root, file_id):
    """Invalidate metadata before physical cleanup, then remove the record."""
    record = workspace_storage.get_file(file_id)
    if record is None:
        raise ValueError(f"No file found with ID {file_id}.")
    storage_key = record[_FILE_STORAGE_KEY_INDEX]

    # Keep an explicit tombstone while byte cleanup is pending. A cleanup
    # failure therefore does not silently turn a live DB record into a missing
    # object reference.
    workspace_storage.update_file_lifecycle_status(file_id, "Invalidated")
    try:
        file_storage.delete_bytes(storage_root, storage_key)
    except Exception as exc:
        raise FileServiceError(
            "File bytes could not be deleted; the metadata record remains Invalidated for safe retry."
        ) from exc

    try:
        workspace_storage.delete_file(file_id)
    except Exception as exc:
        raise FileServiceError(
            "File bytes were deleted, but the Invalidated metadata record could not be removed."
        ) from exc
    return True


def delete_files(storage_root, file_ids):
    unique_ids = list(dict.fromkeys(file_ids))
    if not unique_ids:
        return 0
    if any(not isinstance(file_id, int) for file_id in unique_ids):
        raise ValueError("file_ids must contain only integers.")

    deleted = 0
    for file_id in unique_ids:
        delete_file(storage_root, file_id)
        deleted += 1
    return deleted


def reconcile_storage(storage_root):
    """Find and remove orphaned storage objects without touching live metadata."""
    root = Path(storage_root).expanduser().resolve()
    files_root = root / "files"
    if not files_root.exists():
        return {"orphaned": [], "missing": [], "invalidated": []}

    records = workspace_storage.get_files()
    referenced = {str(record[_FILE_STORAGE_KEY_INDEX]) for record in records}
    missing = []
    invalidated = []
    for record in records:
        key = str(record[_FILE_STORAGE_KEY_INDEX])
        if record[8] == "Invalidated":
            invalidated.append(key)
        elif not file_storage.exists(root, key):
            missing.append(key)

    orphaned = []
    for candidate in files_root.rglob("*"):
        if not candidate.is_file():
            continue
        try:
            relative = candidate.relative_to(root).as_posix()
        except ValueError:
            continue
        if relative not in referenced:
            orphaned.append(relative)

    removed = []
    for key in orphaned:
        try:
            if file_storage.delete_bytes(root, key):
                removed.append(key)
        except OSError:
            continue
    return {"orphaned": orphaned, "removed": removed, "missing": missing, "invalidated": invalidated}
