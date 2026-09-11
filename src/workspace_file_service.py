"""Application service coordinating workspace file metadata and bytes."""

import uuid

import file_storage
import workspace_storage


class FileServiceError(RuntimeError):
    """Raised when file orchestration cannot complete safely."""


def _storage_key():
    return f"files/{uuid.uuid4().hex}"


def create_file(storage_root, project_id, name, data, mime_type=None, folder_id=None):
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data must be bytes-like.")
    payload = bytes(data); storage_key = _storage_key(); digest = file_storage.save_bytes(storage_root, storage_key, payload)
    try:
        file_id = workspace_storage.create_file(project_id=project_id, name=name, storage_key=storage_key, size_bytes=len(payload), sha256=digest, mime_type=mime_type, folder_id=folder_id)
    except Exception:
        try: file_storage.delete_bytes(storage_root, storage_key)
        except Exception as cleanup_error: raise FileServiceError("File metadata creation failed and the newly stored bytes could not be cleaned up.") from cleanup_error
        raise
    return file_id


def replace_file(storage_root, file_id, data, mime_type=None):
    """Replace file bytes atomically from the metadata consumer's perspective."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data must be bytes-like.")
    record = workspace_storage.get_file(file_id)
    if record is None: raise ValueError(f"No file found with ID {file_id}.")
    payload = bytes(data); new_key = _storage_key(); digest = file_storage.save_bytes(storage_root, new_key, payload)
    try:
        workspace_storage.replace_file_record(file_id, new_key, len(payload), digest, mime_type if mime_type is not None else record[5])
    except Exception:
        try: file_storage.delete_bytes(storage_root, new_key)
        except Exception as cleanup_error: raise FileServiceError("File metadata replacement failed and the replacement bytes could not be cleaned up.") from cleanup_error
        raise
    try:
        file_storage.delete_bytes(storage_root, record[4])
    except Exception as exc:
        raise FileServiceError("File metadata now points to the replacement bytes, but the previous byte object could not be cleaned up.") from exc
    return workspace_storage.get_file(file_id)


def delete_file(storage_root, file_id):
    record = workspace_storage.get_file(file_id)
    if record is None: raise ValueError(f"No file found with ID {file_id}.")
    storage_key = record[4]; workspace_storage.delete_file(file_id)
    try: deleted = file_storage.delete_bytes(storage_root, storage_key)
    except Exception as exc: raise FileServiceError("File metadata was deleted, but physical byte cleanup failed; the storage object requires cleanup.") from exc
    return deleted


def delete_files(storage_root, file_ids):
    unique_ids = list(dict.fromkeys(file_ids))
    if not unique_ids: return 0
    if any(not isinstance(file_id, int) for file_id in unique_ids): raise ValueError("file_ids must contain only integers.")
    records = []
    for file_id in unique_ids:
        record = workspace_storage.get_file(file_id)
        if record is None: raise ValueError(f"No file found with ID {file_id}.")
        records.append(record)
    workspace_storage.delete_files(unique_ids); failed_keys = []
    for record in records:
        try: file_storage.delete_bytes(storage_root, record[4])
        except Exception: failed_keys.append(record[4])
    if failed_keys: raise FileServiceError(f"File metadata was deleted, but physical byte cleanup failed for {len(failed_keys)} storage object(s); cleanup is required.")
    return len(records)
