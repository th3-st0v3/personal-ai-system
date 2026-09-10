from dataclasses import dataclass
from typing import Any
from types import MappingProxyType


@dataclass(frozen=True)
class CalculationRecord:
    calculation_type: str
    inputs: dict[str, Any]
    units: dict[str, str]
    assumptions: tuple[str, ...]
    method: str
    result: float
    result_unit: str
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "inputs",
            MappingProxyType(dict(self.inputs)),
        )
        object.__setattr__(
            self,
            "units",
            MappingProxyType(dict(self.units)),
        )
        object.__setattr__(
            self,
            "assumptions",
            tuple(self.assumptions),
        )
