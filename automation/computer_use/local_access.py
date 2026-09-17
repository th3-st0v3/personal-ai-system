from __future__ import annotations

import os
import platform
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class LocalAccessError(RuntimeError):
    """Raised when a local computer capability request is not permitted."""


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    risk: str
    description: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "risk": self.risk, "description": self.description}


CAPABILITIES: tuple[CapabilitySpec, ...] = (
    CapabilitySpec("computer.system.read", "safe", "Read bounded non-secret local runtime metadata."),
    CapabilitySpec("computer.files.list", "safe", "List entries inside explicitly approved workspace roots."),
    CapabilitySpec("computer.files.read", "safe", "Read bounded UTF-8 text files inside explicitly approved workspace roots."),
    CapabilitySpec("computer.browser.chatgpt", "safe", "Observe and control the PASI ChatGPT browser surface through the browser controller boundary."),
    CapabilitySpec("computer.ide.read", "safe", "Read IDE/project state through an explicit IDE adapter boundary."),
    CapabilitySpec("computer.files.write", "approval_required", "Modify local files after an explicit human authorization decision."),
    CapabilitySpec("computer.command.execute", "approval_required", "Execute a command only through an explicit allowlisted execution adapter and approval."),
    CapabilitySpec("computer.application.launch", "approval_required", "Launch an application only after explicit human authorization."),
    CapabilitySpec("computer.desktop.control", "approval_required", "Interact with arbitrary desktop UI only after explicit human authorization."),
    CapabilitySpec("computer.credentials.read", "denied", "Credential and secret material is never exposed to the AI control loop."),
    CapabilitySpec("computer.financial.execute", "denied", "Financial execution is outside the unattended computer-use boundary."),
)

_SECRET_NAME_RE = re.compile(
    r"(^|/)(?:\.env(?:\..*)?|credentials?|secrets?|id_rsa|id_ed25519|authorized_keys)(?:$|[./])|\.(?:pem|key|p12|pfx)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LocalAccessBroker:
    """Least-privilege local read broker with explicit workspace roots."""

    project_root: Path
    allowed_roots: tuple[Path, ...] | None = None
    max_read_bytes: int = 1_000_000
    max_list_entries: int = 500

    def __post_init__(self) -> None:
        project_root = self.project_root.expanduser().resolve()
        if not project_root.is_dir():
            raise LocalAccessError(f"project root is not a directory: {project_root}")
        roots = self.allowed_roots if self.allowed_roots is not None else self._roots_from_environment(project_root)
        normalized = tuple(dict.fromkeys(root.expanduser().resolve() for root in roots))
        if not normalized:
            normalized = (project_root,)
        if self.max_read_bytes <= 0 or self.max_list_entries <= 0:
            raise LocalAccessError("local access bounds must be positive")
        object.__setattr__(self, "project_root", project_root)
        object.__setattr__(self, "allowed_roots", normalized)

    @staticmethod
    def _roots_from_environment(project_root: Path) -> tuple[Path, ...]:
        raw = os.environ.get("PASI_ALLOWED_ROOTS", "").strip()
        configured = tuple(Path(item) for item in raw.split(os.pathsep) if item.strip()) if raw else ()
        return tuple(dict.fromkeys((project_root, *configured)))

    def capabilities(self) -> list[dict[str, str]]:
        return [capability.to_dict() for capability in CAPABILITIES]

    def system_info(self) -> dict[str, Any]:
        return {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
            "executable": sys.executable,
            "working_directory": str(Path.cwd().resolve()),
            "project_root": str(self.project_root),
            "allowed_roots": [str(root) for root in self.allowed_roots or ()],
            "read_only": True,
        }

    def list_directory(self, requested: str = "", *, limit: int | None = None) -> list[dict[str, str]]:
        directory = self._resolve(requested)
        if not directory.is_dir():
            raise LocalAccessError(f"directory does not exist: {requested or directory}")
        self._reject_sensitive(directory)
        effective_limit = self.max_list_entries if limit is None else limit
        if not 1 <= effective_limit <= self.max_list_entries:
            raise LocalAccessError(f"directory listing limit must be between 1 and {self.max_list_entries}")
        result: list[dict[str, str]] = []
        for entry in sorted(directory.iterdir(), key=lambda item: item.name.casefold())[:effective_limit]:
            if self._is_sensitive(entry):
                continue
            try:
                resolved = entry.resolve()
            except OSError:
                continue
            if not self._under_allowed_root(resolved):
                continue
            kind = "directory" if resolved.is_dir() else "file" if resolved.is_file() else "other"
            result.append({"name": entry.name, "type": kind})
        return result

    def read_text(self, requested: str, *, max_chars: int | None = None) -> dict[str, Any]:
        path = self._resolve(requested)
        if not path.is_file():
            raise LocalAccessError(f"file does not exist: {requested}")
        self._reject_sensitive(path)
        effective_chars = self.max_read_bytes if max_chars is None else max_chars
        if not 1 <= effective_chars <= self.max_read_bytes:
            raise LocalAccessError(f"read limit must be between 1 and {self.max_read_bytes}")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise LocalAccessError(f"could not read file: {requested}") from exc
        truncated_bytes = len(raw) > self.max_read_bytes
        raw = raw[: self.max_read_bytes]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LocalAccessError("local file is not UTF-8 text") from exc
        truncated = truncated_bytes or len(text) > effective_chars
        if len(text) > effective_chars:
            text = text[:effective_chars]
        return {"path": str(path), "content": text, "truncated": truncated, "bytes_returned": len(raw)}

    def _resolve(self, requested: str) -> Path:
        value = str(requested or "").strip()
        candidates: list[Path] = []
        if value:
            raw = Path(value).expanduser()
            candidates = [raw] if raw.is_absolute() else [root / raw for root in self.allowed_roots or ()]
        else:
            candidates = list(self.allowed_roots or ())
        fallback: Path | None = None
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError as exc:
                raise LocalAccessError("unable to resolve local path") from exc
            if not self._under_allowed_root(resolved):
                continue
            if fallback is None:
                fallback = resolved
            if resolved.exists():
                return resolved
        if fallback is not None:
            return fallback
        raise LocalAccessError("path is outside the configured PASI workspace roots")

    def _under_allowed_root(self, path: Path) -> bool:
        return any(path == root or root in path.parents for root in self.allowed_roots or ())

    def _is_sensitive(self, path: Path) -> bool:
        normalized = path.as_posix()
        return bool(_SECRET_NAME_RE.search(normalized)) or ".git" in path.parts

    def _reject_sensitive(self, path: Path) -> None:
        if self._is_sensitive(path):
            raise LocalAccessError("secret, credential, or repository-internal metadata is outside the local read boundary")
