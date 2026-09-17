from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from .simulation_library import SIMULATION_SCHEMA_VERSION, _fingerprint, get_simulation


VerificationStatus = Literal["verified", "failed", "inconclusive"]


@dataclass(frozen=True)
class SimulationVerification:
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


def _mapping(value: object, label: str) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def verify_simulation_result(result: Mapping[str, object]) -> SimulationVerification:
    """Verify the structural and cryptographic self-consistency of a simulation result."""
    checks: list[str] = []
    failures: list[str] = []

    schema_version = result.get("schema_version")
    if schema_version != SIMULATION_SCHEMA_VERSION:
        failures.append("schema_version does not match the supported simulation schema")
    else:
        checks.append("schema_version")

    key = result.get("key")
    provenance = _mapping(result.get("provenance"), "provenance")
    outputs = _mapping(result.get("outputs"), "outputs")
    inputs = _mapping(result.get("inputs"), "inputs")

    if not isinstance(key, str):
        failures.append("simulation key is missing")
    else:
        try:
            get_simulation(key)
            checks.append("known simulation key")
        except ValueError:
            failures.append("simulation key is not registered")

    if provenance is None:
        failures.append("provenance is missing or not an object")
    else:
        checks.append("provenance shape")

    if outputs is None:
        failures.append("outputs are missing or not an object")
    else:
        non_finite = [
            name
            for name, value in outputs.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isfinite(float(value))
        ]
        non_numeric = [
            name
            for name, value in outputs.items()
            if not isinstance(value, (int, float)) or isinstance(value, bool)
        ]
        if non_finite:
            failures.append(f"outputs contain non-finite values: {', '.join(map(str, non_finite))}")
        elif non_numeric:
            failures.append(f"outputs contain non-numeric values: {', '.join(map(str, non_numeric))}")
        else:
            checks.append("finite numeric outputs")

    if inputs is None:
        failures.append("inputs are missing or not an object")
    else:
        invalid_inputs = [
            name
            for name, value in inputs.items()
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value))
        ]
        if invalid_inputs:
            failures.append(f"inputs contain invalid values: {', '.join(map(str, invalid_inputs))}")
        else:
            checks.append("finite numeric inputs")

    if provenance is not None and isinstance(key, str) and inputs is not None and outputs is not None:
        if provenance.get("simulation_key") != key:
            failures.append("provenance simulation key does not match result key")
        else:
            checks.append("simulation key provenance match")

        expected_output_fingerprint = provenance.get("output_fingerprint")
        if not isinstance(expected_output_fingerprint, str):
            failures.append("provenance output fingerprint is missing")
        elif expected_output_fingerprint != _fingerprint(outputs):
            failures.append("simulation outputs do not match the recorded output fingerprint")
        else:
            checks.append("output fingerprint")

        expected_fingerprint = provenance.get("fingerprint")
        if not isinstance(expected_fingerprint, str):
            failures.append("provenance fingerprint is missing")
        else:
            fingerprint_payload = dict(provenance)
            fingerprint_payload.pop("fingerprint", None)
            if expected_fingerprint != _fingerprint(fingerprint_payload):
                failures.append("provenance fingerprint does not match the recorded evidence")
            else:
                checks.append("provenance fingerprint")

    status: VerificationStatus
    if failures:
        status = "failed"
    elif not checks:
        status = "inconclusive"
    else:
        status = "verified"

    return SimulationVerification(
        status=status,
        checks=tuple(checks),
        failures=tuple(failures),
    )


__all__ = ["SimulationVerification", "VerificationStatus", "verify_simulation_result"]
