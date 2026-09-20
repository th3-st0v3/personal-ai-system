from __future__ import annotations

import os
from pathlib import Path

DEFAULT_STATE_ROOT = Path.home() / ".pasi" / "state"
STATE_ROOT_ENV = "PASI_STATE_ROOT"


def resolve_state_root(repo_root: Path | None = None, configured: Path | None = None) -> Path:
    root = configured
    if root is None:
        raw = os.environ.get(STATE_ROOT_ENV, "").strip()
        root = Path(raw).expanduser() if raw else DEFAULT_STATE_ROOT
    if not root.is_absolute():
        raise ValueError(f"{STATE_ROOT_ENV} must be an absolute path")
    resolved = root.resolve()
    if repo_root is not None:
        repo = repo_root.expanduser().resolve()
        if resolved == repo or repo in resolved.parents:
            raise ValueError(f"{STATE_ROOT_ENV} must not be inside the editable repository/worktree")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def resolve_state_path(
    configured: Path | None,
    *,
    state_root: Path,
    repo_root: Path,
) -> Path:
    if configured is None:
        raise ValueError("configured state path is required")
    path = configured.expanduser()
    if not path.is_absolute():
        path = state_root / path
    resolved = path.resolve()
    repo = repo_root.expanduser().resolve()
    if resolved == repo or repo in resolved.parents:
        raise ValueError("state path must not be inside the editable repository/worktree")
    return resolved
