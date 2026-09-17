from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .obstacles import ObstacleLedger

DEFAULT_POLICY_PATH = ".runtime/policy/preapprovals.json"
DEFAULT_ACQUISITION_DIR = ".runtime/acquired"
MAX_POLICY_BYTES = 100_000
MAX_DOWNLOAD_BYTES = 25_000_000
MAX_PACKAGE_OUTPUT = 8_000

_PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?(?:==|>=|<=|~=|>|<)[A-Za-z0-9.*+!-]+$")


class AcquisitionError(RuntimeError):
    """Raised when a preapproved acquisition cannot be completed safely."""


@dataclass(frozen=True)
class ApprovalDecision:
    allowed: bool
    approval_id: str | None
    reason: str


@dataclass
class PreapprovalPolicy:
    repo_root: Path
    policy_path: Path | None = None

    def __post_init__(self) -> None:
        self.repo_root = self.repo_root.expanduser().resolve()
        configured = self.policy_path
        if configured is None:
            configured = Path(os.environ.get("PASI_PREAPPROVALS_PATH", DEFAULT_POLICY_PATH))
        if not configured.is_absolute():
            configured = self.repo_root / configured
        self.policy_path = configured.resolve()

    def _load(self) -> dict[str, Any]:
        policy_path = self.policy_path
        if policy_path is None:
            raise AcquisitionError("preapproval policy path is not configured")
        try:
            if policy_path.stat().st_size > MAX_POLICY_BYTES:
                raise AcquisitionError("preapproval policy is too large")
            raw = json.loads(policy_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"schema_version": 1, "approvals": []}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AcquisitionError("preapproval policy could not be read") from exc
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise AcquisitionError("unsupported preapproval policy schema")
        approvals = raw.get("approvals", [])
        if not isinstance(approvals, list):
            raise AcquisitionError("preapproval approvals must be a list")
        return raw

    @staticmethod
    def _valid_until(value: Any) -> bool:
        if not value:
            return True
        if not isinstance(value, str):
            return False
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < stamp

    def approve_public_download(self, url: str, *, max_bytes: int) -> ApprovalDecision:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            return ApprovalDecision(False, None, "public downloads require an HTTPS URL")
        if not 1 <= max_bytes <= MAX_DOWNLOAD_BYTES:
            return ApprovalDecision(False, None, f"max_bytes must be between 1 and {MAX_DOWNLOAD_BYTES}")
        for item in self._load().get("approvals", []):
            if not isinstance(item, Mapping) or item.get("action") != "public_download" or not self._valid_until(item.get("expires_at")):
                continue
            hosts = item.get("hosts", [])
            if not isinstance(hosts, list) or parsed.hostname.lower() not in {str(host).lower().lstrip(".") for host in hosts}:
                continue
            limit_value = item.get("max_bytes", max_bytes)
            limit = int(limit_value) if isinstance(limit_value, int) or (isinstance(limit_value, str) and limit_value.isdigit()) else max_bytes
            if max_bytes > limit:
                continue
            return ApprovalDecision(True, str(item.get("id", "unnamed")), "matching HTTPS host preapproval")
        return ApprovalDecision(False, None, f"no active preapproval authorizes HTTPS host {parsed.hostname}")

    def approve_package_install(self, package: str) -> ApprovalDecision:
        package = package.strip()
        if not _PACKAGE_RE.fullmatch(package) or "==" not in package:
            return ApprovalDecision(False, None, "package must be an exact version-pinned requirement such as package==1.2.3")
        normalized = package.casefold()
        for item in self._load().get("approvals", []):
            if not isinstance(item, Mapping) or item.get("action") != "package_install" or not self._valid_until(item.get("expires_at")):
                continue
            packages = item.get("packages", [])
            if not isinstance(packages, list):
                continue
            if normalized in {str(candidate).strip().casefold() for candidate in packages} and str(item.get("manager", "pip")) == "pip":
                return ApprovalDecision(True, str(item.get("id", "unnamed")), "exact package preapproval")
        return ApprovalDecision(False, None, f"no active preapproval authorizes package {package}")


@dataclass
class AcquisitionEngine:
    repo_root: Path
    policy: PreapprovalPolicy | None = None
    obstacles: ObstacleLedger | None = None
    acquisition_dir: Path | None = None

    def __post_init__(self) -> None:
        self.repo_root = self.repo_root.expanduser().resolve()
        self.policy = self.policy or PreapprovalPolicy(self.repo_root)
        self.obstacles = self.obstacles or ObstacleLedger(self.repo_root)
        directory = self.acquisition_dir or (self.repo_root / DEFAULT_ACQUISITION_DIR)
        self.acquisition_dir = directory.resolve()

    def _blocked(self, kind: str, target: str, reason: str, *, task_id: str = "") -> dict[str, Any]:
        obstacles = self.obstacles
        if obstacles is None:
            raise AcquisitionError("obstacle ledger is not configured")
        obstacle = obstacles.record(
            "preapproval_required",
            f"Preapproval required for {kind}: {target}",
            f"Review the request and add a narrowly scoped preapproval if this acquisition is intended. Reason: {reason}",
            task_id=task_id,
            status="needs_preapproval",
            details={"kind": kind, "target": target, "reason": reason},
        )
        return {"status": "blocked", "reason": reason, "obstacle_id": obstacle.obstacle_id, "approval_required": True}

    def acquire_public_download(
        self,
        url: str,
        *,
        filename: str | None = None,
        expected_sha256: str | None = None,
        max_bytes: int = 5_000_000,
        task_id: str = "",
    ) -> dict[str, Any]:
        policy = self.policy
        if policy is None:
            raise AcquisitionError("preapproval policy is not configured")
        decision = policy.approve_public_download(url, max_bytes=max_bytes)
        if not decision.allowed:
            return self._blocked("public_download", url, decision.reason, task_id=task_id)
        parsed = urlparse(url)
        name = filename or Path(parsed.path).name or "download.bin"
        name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120]
        if not name or name in {".", ".."}:
            name = "download.bin"
        acquisition_dir = self.acquisition_dir
        if acquisition_dir is None:
            raise AcquisitionError("acquisition directory is not configured")
        acquisition_dir.mkdir(parents=True, exist_ok=True)
        destination = (acquisition_dir / name).resolve()
        if acquisition_dir not in destination.parents:
            raise AcquisitionError("download destination escaped acquisition directory")
        if max_bytes <= 0 or max_bytes > MAX_DOWNLOAD_BYTES:
            raise AcquisitionError(f"max_bytes must be between 1 and {MAX_DOWNLOAD_BYTES}")

        digest = hashlib.sha256()
        total = 0
        temp = destination.with_suffix(destination.suffix + ".part")
        try:
            request = Request(url, headers={"User-Agent": "PASI-resource-acquirer/1"})
            with urlopen(request, timeout=30) as response:
                final_url = response.geturl()
                final_decision = policy.approve_public_download(final_url, max_bytes=max_bytes)
                if not final_decision.allowed:
                    raise AcquisitionError(f"download redirect escaped the approved HTTPS host: {final_url}")
                with temp.open("wb") as handle:
                    while True:
                        chunk = response.read(min(1024 * 1024, max_bytes - total + 1))
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise AcquisitionError("download exceeded preapproved byte limit")
                        digest.update(chunk)
                        handle.write(chunk)
            actual_sha256 = digest.hexdigest()
            if expected_sha256 and actual_sha256.casefold() != expected_sha256.strip().casefold():
                raise AcquisitionError("download SHA-256 did not match the requested digest")
            temp.replace(destination)
        except Exception:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            raise
        return {
            "status": "ok",
            "kind": "public_download",
            "approval_id": decision.approval_id,
            "path": str(destination),
            "bytes": total,
            "sha256": digest.hexdigest(),
        }

    def install_python_package(self, package: str, *, task_id: str = "") -> dict[str, Any]:
        policy = self.policy
        obstacles = self.obstacles
        if policy is None or obstacles is None:
            raise AcquisitionError("acquisition policy is not configured")
        decision = policy.approve_package_install(package)
        if not decision.allowed:
            return self._blocked("package_install", package, decision.reason, task_id=task_id)
        executable = Path(sys.executable).resolve()
        result = subprocess.run(
            [str(executable), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--no-deps", package],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        if result.returncode != 0:
            obstacles.record(
                "acquisition_failed",
                f"Preapproved package installation failed: {package}",
                "Review the package/version and environment; retry only after the failure cause is understood.",
                task_id=task_id,
                status="pending",
                details={"approval_id": decision.approval_id, "exit_code": result.returncode, "output": output[-MAX_PACKAGE_OUTPUT:]},
            )
            return {"status": "error", "approval_id": decision.approval_id, "exit_code": result.returncode, "output": output[-MAX_PACKAGE_OUTPUT:]}
        return {"status": "ok", "kind": "package_install", "approval_id": decision.approval_id, "package": package, "output": output[-MAX_PACKAGE_OUTPUT:]}
