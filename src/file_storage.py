"""Local byte storage for workspace files.

This module owns physical file bytes only. Workspace metadata remains in
``workspace_storage`` and refers to bytes through a stable ``storage_key``.
"""

import hashlib
import os
import tempfile
from pathlib import Path


_CHUNK_SIZE = 1024 * 1024


def _require_storage_key(storage_key):
    if not isinstance(storage_key, str) or not storage_key.strip():
        raise ValueError("storage_key must be a non-empty string.")
    key = storage_key.strip().replace("\\", "/")
    path = Path(key)
    if path.is_absolute() or ".." in path.parts or any(part == "" for part in path.parts):
        raise ValueError("storage_key must be a relative path without empty or parent components.")
    return key


def _resolve_path(root, storage_key):
    key = _require_storage_key(storage_key)
    root_path = Path(root).expanduser().resolve()
    target = (root_path / key).resolve()
    if target != root_path and root_path not in target.parents:
        raise ValueError("storage_key resolves outside the storage root.")
    return target


def storage_path(storage_root, storage_key):
    """Return the safe physical path for a storage key."""
    return _resolve_path(storage_root, storage_key)


def save_bytes(storage_root, storage_key, data):
    """Atomically store bytes and return their SHA-256 digest."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data must be bytes-like.")
    payload = bytes(data)
    target = _resolve_path(storage_root, storage_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(payload).hexdigest()

    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return digest


def read_bytes(storage_root, storage_key):
    """Read stored bytes or raise ``FileNotFoundError``."""
    return _resolve_path(storage_root, storage_key).read_bytes()


def delete_bytes(storage_root, storage_key):
    """Delete stored bytes if present and report whether they existed."""
    target = _resolve_path(storage_root, storage_key)
    try:
        target.unlink()
    except FileNotFoundError:
        return False
    return True


def exists(storage_root, storage_key):
    """Return whether a stored object exists as a regular file."""
    return _resolve_path(storage_root, storage_key).is_file()


def verify_sha256(storage_root, storage_key, expected_sha256):
    """Verify a stored object's SHA-256 digest without loading it all at once."""
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ValueError("expected_sha256 must be a 64-character hexadecimal digest.")
    expected = expected_sha256.lower()
    try:
        int(expected, 16)
    except ValueError as exc:
        raise ValueError("expected_sha256 must be a 64-character hexadecimal digest.") from exc

    digest = hashlib.sha256()
    with _resolve_path(storage_root, storage_key).open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest() == expected
