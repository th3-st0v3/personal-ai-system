from dataclasses import dataclass


@dataclass(frozen=True)
class CalculationModel:
    """Stable identity and metadata for an engineering calculation model."""

    key: str
    name: str
    domain: str
    description: str
    model_type: str

    def __post_init__(self) -> None:
        for field_name in ("key", "name", "domain", "description", "model_type"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")


@dataclass(frozen=True)
class MethodVersion:
    """Exact versioned method definition used by a calculation model."""

    calculation_model_key: str
    version: str
    equation: str
    description: str
    applicability: str
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "calculation_model_key",
            "version",
            "equation",
            "description",
            "applicability",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        object.__setattr__(self, "assumptions", tuple(self.assumptions))
        object.__setattr__(self, "limitations", tuple(self.limitations))


@dataclass(frozen=True)
class CalculationParameter:
    """Definition of an input accepted by a calculation model."""

    calculation_model_key: str
    name: str
    description: str
    data_type: str
    required: bool
    dimension: str
    minimum: float | None = None
    maximum: float | None = None
    default_unit: str | None = None

    def __post_init__(self) -> None:
        if not self.calculation_model_key.strip():
            raise ValueError("calculation_model_key must not be empty")
        for field_name in ("name", "description", "data_type", "dimension"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("minimum must not exceed maximum")
