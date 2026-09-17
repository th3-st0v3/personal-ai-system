from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from automation.computer_use.contracts import ActionProposal, Observation


VerificationStatus = Literal["verified", "failed", "inconclusive"]


@dataclass(frozen=True)
class WorkerVerification:
    status: VerificationStatus
    checks: tuple[str, ...]
    failures: tuple[str, ...]

    @property
    def verified(self) -> bool:
        return self.status == "verified"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "verified": self.verified,
            "checks": list(self.checks),
            "failures": list(self.failures),
        }


class WorkerVerifier(Protocol):
    """Deterministic post-execution verification seam for worker observations."""

    def verify(self, action: ActionProposal, observation: Observation) -> WorkerVerification: ...


def verify_worker_observation(
    action: ActionProposal,
    observation: Observation,
) -> WorkerVerification:
    """Perform bounded structural checks without inventing domain semantics."""
    checks: list[str] = []
    failures: list[str] = []

    if observation.session_id != action.session_id:
        failures.append("observation session does not match action session")
    else:
        checks.append("session match")

    for field_name, value in (
        ("observation_id", observation.observation_id),
        ("source", observation.source),
        ("kind", observation.kind),
    ):
        if not value.strip():
            failures.append(f"observation {field_name} is empty")
        else:
            checks.append(field_name)

    fingerprint = observation.fingerprint()
    if len(fingerprint) != 64:
        failures.append("observation fingerprint is not a SHA-256 digest")
    else:
        checks.append("observation fingerprint")

    return WorkerVerification(
        status="failed" if failures else "verified",
        checks=tuple(checks),
        failures=tuple(failures),
    )


class DeterministicWorkerVerifier:
    """Default provider-neutral verifier used by the persistent worker."""

    def verify(self, action: ActionProposal, observation: Observation) -> WorkerVerification:
        return verify_worker_observation(action, observation)


__all__ = [
    "DeterministicWorkerVerifier",
    "WorkerVerification",
    "WorkerVerifier",
    "VerificationStatus",
    "verify_worker_observation",
]
