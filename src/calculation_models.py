from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class CalculationModel:
    """Stable definition of an engineering calculation model."""

    name: str
    domain: str
    description: str
    model_type: str


@dataclass(frozen=True)
class MethodVersion:
    """Versioned engineering method used by a calculation model."""

    calculation_model_id: int
    version: str
    equation: str
    description: str
    applicability: str
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    source_id: int | None = None

    def __post_init__(self) -> None:
        if self.calculation_model_id <= 0:
            raise ValueError("calculation_model_id must be positive")
        if not self.version.strip():
            raise ValueError("version must not be empty")
        if not self.equation.strip():
            raise ValueError("equation must not be empty")
        if self.source_id is not None and self.source_id <= 0:
            raise ValueError("source_id must be positive when provided")

        object.__setattr__(self, "assumptions", tuple(self.assumptions))
        object.__setattr__(self, "limitations", tuple(self.limitations))


@dataclass(frozen=True)
class CalculationParameter:
    """Definition of an input accepted by a calculation model."""

    calculation_model_id: int
    name: str
    description: str
    data_type: str
    required: bool
    dimension: str
    minimum: float | None = None
    maximum: float | None = None
    default_unit: str | None = None

    def __post_init__(self) -> None:
        if self.calculation_model_id <= 0:
            raise ValueError("calculation_model_id must be positive")
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if not self.data_type.strip():
            raise ValueError("data_type must not be empty")
        if not self.dimension.strip():
            raise ValueError("dimension must not be empty")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("minimum must not exceed maximum")


@dataclass(frozen=True)
class FluidModel:
    """Named and versioned fluid-property model used by engineering methods."""

    name: str
    fluid_type: str
    model_type: str
    parameters: dict[str, Any]
    version: str
    source_id: int | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if not self.fluid_type.strip():
            raise ValueError("fluid_type must not be empty")
        if not self.model_type.strip():
            raise ValueError("model_type must not be empty")
        if not self.version.strip():
            raise ValueError("version must not be empty")
        if self.source_id is not None and self.source_id <= 0:
            raise ValueError("source_id must be positive when provided")

        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(self.parameters)),
        )
