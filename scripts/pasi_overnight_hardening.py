from __future__ import annotations

import re
from pathlib import Path

from scripts import pasi_overnight_engine as engine
from scripts import pasi_overnight_engine_v2 as supervisor


_FORBIDDEN_PATH_PARTS = frozenset({".git", ".env", ".env.local", ".env.production"})
_FORBIDDEN_PATH_PATTERNS = (
    re.compile(r"(^|/)(id_rsa|id_ed25519|authorized_keys)$", re.IGNORECASE),
    re.compile(r"(^|/)(credentials|secrets?)(\.|/|$)", re.IGNORECASE),
)
_DIFF_PATH_RE = re.compile(r"^diff --git a/(.+) b/(.+)$", re.MULTILINE)
_DELETION_FILE_HEADER_RE = re.compile(r"^(?:deleted file mode \d+\n)?--- a/[^\n]+\n\+\+\+ /dev/null$", re.MULTILINE)


def validate_patch_paths(patch: str, allow_delete: bool) -> None:
    if len(patch.encode("utf-8")) > engine.MAX_PATCH_BYTES:
        raise ValueError("model patch exceeds configured size bound")
    if "new file mode 120000" in patch or "new file mode 160000" in patch:
        raise ValueError("symlink and submodule additions are not allowed in unattended patches")

    matches = _DIFF_PATH_RE.findall(patch)
    if not matches:
        raise ValueError("model response did not contain a unified git diff")

    for old_path, new_path in matches:
        for path_value in (old_path, new_path):
            if path_value == "/dev/null":
                continue
            normalized = path_value.replace("\\", "/")
            parts = Path(normalized).parts
            if normalized.startswith("/") or ".." in parts:
                raise ValueError(f"unsafe patch path: {path_value}")
            if any(part in _FORBIDDEN_PATH_PARTS for part in parts):
                raise ValueError(f"forbidden patch path: {path_value}")
            if any(pattern.search(normalized) for pattern in _FORBIDDEN_PATH_PATTERNS):
                raise ValueError(f"forbidden credential/secret path: {path_value}")

    is_deletion = bool(_DELETION_FILE_HEADER_RE.search(patch)) or bool(
        re.search(r"^--- [^\n]+\n\+\+\+ /dev/null$", patch, re.MULTILINE)
    )
    if is_deletion and not allow_delete:
        raise ValueError("file deletion requires PASI_RESULT_ALLOW_DELETE: true")


def main() -> int:
    supervisor.validate_patch_paths = validate_patch_paths
    return supervisor.main()
