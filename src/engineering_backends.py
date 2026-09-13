"""Stable adapter contracts for engineering compute backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from engineering_runtime import RunManifest, WorkloadSpec, authorize_workload


@dataclass(frozen=True)
class BackendResult:
    """Backend-neutral result payload with optional verification data."""

    outputs: dict[str, Any]
    metadata: dict[str, Any]
    checks: tuple[str, ...] = ()


class EngineeringBackend(Protocol):
    """Contract implemented by local, accelerator, cluster, and HPC adapters."""

    name: str

    def supports(self, spec: WorkloadSpec) -> bool:
        """Return whether this backend can execute the workload."""
        ...

    def execute(self, spec: WorkloadSpec) -> tuple[RunManifest, BackendResult]:
        """Execute an authorized workload and return its manifest and result."""
        ...


def validate_backend_selection(spec: WorkloadSpec, backend: EngineeringBackend, *, remote: bool = False, network: bool = False) -> None:
    """Apply the workload policy before selecting an execution backend."""
    authorize_workload(spec, remote=remote, network=network)
    if not backend.supports(spec):
        raise ValueError(f"backend '{backend.name}' does not support workload kind '{spec.kind}'")
