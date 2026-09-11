# Local Byte Storage

`src/file_storage.py` is the physical-byte storage boundary for workspace files.

## Contract

The module accepts a configured storage root and a relative `storage_key`. It provides:

- `storage_path(root, key)` — resolve a validated key inside the root.
- `save_bytes(root, key, data)` — atomically write bytes and return their SHA-256 digest.
- `read_bytes(root, key)` — read an object.
- `exists(root, key)` — check for a regular file.
- `delete_bytes(root, key)` — delete an object and return whether it existed.
- `verify_sha256(root, key, digest)` — stream-hash an object and compare it with the expected digest.

## Safety boundary

A storage key is an identifier, not an arbitrary filesystem path. Absolute paths, parent-directory traversal, empty path components, and Windows drive-qualified paths are rejected. Resolved paths are checked to remain beneath the configured root, including symlink resolution.

Writes use a temporary file in the destination directory, flush and `fsync`, then atomic replacement. This prevents normal interrupted writes from leaving a partially written destination object.

## Separation from workspace metadata

The byte layer intentionally does not import the database or workspace metadata layer. A file record can therefore retain its stable `storage_key` while the physical storage implementation changes from local disk to another backend later.

Deleting a metadata record does not implicitly delete bytes. A higher-level application service should coordinate those operations when the product has explicit recovery and failure semantics for physical storage cleanup.
