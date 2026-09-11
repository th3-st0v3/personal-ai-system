from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class CalculationRecord:
    """Immutable record of one deterministic calculation execution."""

    calculation_type: str
    inputs: dict[str, Any]
    units: dict[str, str]
    assumptions: tuple[str, ...]
    method: str
    result: float
    result_unit: str
    source: str
    method_version: str | None = None

    def __post_init__(self) -> None:
        if not self.calculation_type.strip():
            raise ValueError("calculation_type must not be empty")
        if not self.method.strip():
            raise ValueError("method must not be empty")
        if not self.result_unit.strip():
            raise ValueError("result_unit must not be empty")
        if not self.source.strip():
            raise ValueError("source must not be empty")
        if self.method_version is not None and not self.method_version.strip():
            raise ValueError("method_version must not be empty when provided")

        object.__setattr__(self, "inputs", MappingProxyType(dict(self.inputs)))
        object.__setattr__(self, "units", MappingProxyType(dict(self.units)))
        object.__setattr__(self, "assumptions", tuple(self.assumptions))
