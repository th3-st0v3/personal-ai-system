"""Backend-neutral engineering workload contracts.

The runtime is intentionally an orchestration layer, not a solver. Numerical,
CAD, AI, and HPC backends can implement these contracts without sharing an
implementation language or forcing the application layer to know how they
execute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Literal

WorkloadKind = Literal["calculation", "simulation", "optimization", "surrogate", "cad", "ai", "verification"]
ExecutionTier = Literal["local-cpu", "local-accelerator", "multi-device", "cluster", "hpc", "cloud"]


@dataclass(frozen=True)
class ResourceProfile:
    """Requested resource envelope for one engineering workload."""

    cpu_cores: int = 1
    memory_mb: int = 256
    accelerator_count: int = 0
    accelerator_memory_mb: int = 0
    execution_tiers: tuple[ExecutionTier, ...] = ("local-cpu",)
    network_required: bool = False

    def __post_init__(self) -> None:
        if self.cpu_cores < 1 or self.memory_mb < 1:
            raise ValueError("cpu_cores and memory_mb must be positive")
        if self.accelerator_count < 0 or self.accelerator_memory_mb < 0:
            raise ValueError("accelerator resources must not be negative")
        tiers = tuple(self.execution_tiers)
        if not tiers:
            raise ValueError("execution_tiers must not be empty")
        object.__setattr__(self, "execution_tiers", tiers)


@dataclass(frozen=True)
class ExecutionPolicy:
    """Safety and reproducibility constraints applied before execution."""

    deterministic: bool = True
    checkpoint_required: bool = True
    allow_remote: bool = False
    allow_network: bool = False
    approval_required: bool = False
    max_runtime_seconds: int = 3600

    def __post_init__(self) -> None:
        if self.max_runtime_seconds < 1:
            raise ValueError("max_runtime_seconds must be positive")
        if self.allow_network and not self.allow_remote:
            raise ValueError("network access requires remote execution")


@dataclass(frozen=True)
class WorkloadSpec:
    """Canonical description of a schedulable engineering computation."""

    name: str
    kind: WorkloadKind
    inputs: dict[str, Any] = field(default_factory=dict)
    resource_profile: ResourceProfile = field(default_factory=ResourceProfile)
    policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    tags: tuple[str, ...] = ()
    software_version: str = "local"

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.software_version.strip():
            raise ValueError("name and software_version must not be empty")
        object.__setattr__(self, "inputs", dict(self.inputs))
        object.__setattr__(self, "tags", tuple(tag.strip() for tag in self.tags if tag.strip()))

    def canonical_payload(self) -> dict[str, Any]:
        resources = self.resource_profile
        policy = self.policy
        return {
            "name": self.name,
            "kind": self.kind,
            "inputs": self.inputs,
            "resource_profile": {
                "cpu_cores": resources.cpu_cores,
                "memory_mb": resources.memory_mb,
                "accelerator_count": resources.accelerator_count,
                "accelerator_memory_mb": resources.accelerator_memory_mb,
                "execution_tiers": resources.execution_tiers,
                "network_required": resources.network_required,
            },
            "policy": {
                "deterministic": policy.deterministic,
                "checkpoint_required": policy.checkpoint_required,
                "allow_remote": policy.allow_remote,
                "allow_network": policy.allow_network,
                "approval_required": policy.approval_required,
                "max_runtime_seconds": policy.max_runtime_seconds,
            },
            "tags": self.tags,
            "software_version": self.software_version,
        }

    def fingerprint(self) -> str:
        """Return a stable SHA-256 fingerprint of the workload definition."""
        encoded = json.dumps(
            self.canonical_payload(), sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class RunManifest:
    """Immutable execution metadata that can accompany a stored result."""

    workload_fingerprint: str
    backend: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    started_at: str | None = None
    finished_at: str | None = None
    result_fingerprint: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if len(self.workload_fingerprint) != 64:
            raise ValueError("workload_fingerprint must be a SHA-256 hex digest")
        try:
            int(self.workload_fingerprint, 16)
        except ValueError as exc:
            raise ValueError("workload_fingerprint must be hexadecimal") from exc
        if not self.backend.strip():
            raise ValueError("backend must not be empty")
        if self.status == "succeeded" and not self.result_fingerprint:
            raise ValueError("successful runs require result_fingerprint")
        if self.status == "failed" and not self.error:
            raise ValueError("failed runs require an error")


def authorize_workload(spec: WorkloadSpec, *, remote: bool = False, network: bool = False) -> None:
    """Reject execution requests that exceed the declared workload policy."""
    if remote and not spec.policy.allow_remote:
        raise PermissionError("remote execution is not permitted by the workload policy")
    if network and not spec.policy.allow_network:
        raise PermissionError("network access is not permitted by the workload policy")
    if spec.resource_profile.network_required and not network:
        raise PermissionError("workload requires network access but it was not granted")
