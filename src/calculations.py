from calculation_definitions import (
    DARCY_METHOD,
    DARCY_MODEL,
    HYDROSTATIC_METHOD,
    HYDROSTATIC_MODEL,
    HYDROSTATIC_PARAMETERS,
)
from calculation_records import CalculationRecord


def _validate_non_negative(name: str, value: float) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def hydrostatic_pressure(
    density_kg_m3: float,
    gravity_m_s2: float,
    depth_m: float,
) -> float:
    """Calculate hydrostatic pressure: P = rho * g * h."""
    _validate_non_negative("density", density_kg_m3)
    _validate_non_negative("gravity", gravity_m_s2)
    _validate_non_negative("depth", depth_m)
    return density_kg_m3 * gravity_m_s2 * depth_m


def hydrostatic_pressure_record(
    density_kg_m3: float,
    gravity_m_s2: float,
    depth_m: float,
) -> CalculationRecord:
    """Calculate hydrostatic pressure and return a reproducible record."""
    result = hydrostatic_pressure(density_kg_m3, gravity_m_s2, depth_m)
    return CalculationRecord(
        calculation_type=HYDROSTATIC_MODEL.key,
        inputs={"density": density_kg_m3, "gravity": gravity_m_s2, "depth": depth_m},
        units={parameter.name: parameter.default_unit or "" for parameter in HYDROSTATIC_PARAMETERS},
        assumptions=HYDROSTATIC_METHOD.assumptions,
        method=HYDROSTATIC_METHOD.equation,
        result=result,
        result_unit="Pa",
        source="deterministic calculation",
        method_version=HYDROSTATIC_METHOD.version,
    )


def darcy_weisbach_pressure_loss(
    friction_factor: float,
    pipe_length_m: float,
    pipe_diameter_m: float,
    density_kg_m3: float,
    velocity_m_s: float,
) -> float:
    """Calculate pressure loss using the Darcy-Weisbach equation."""
    _validate_non_negative("friction factor", friction_factor)
    _validate_non_negative("pipe length", pipe_length_m)
    _validate_non_negative("pipe diameter", pipe_diameter_m)
    _validate_non_negative("density", density_kg_m3)
    _validate_non_negative("velocity", velocity_m_s)
    if pipe_diameter_m == 0:
        raise ValueError("pipe diameter must be greater than zero")
    return friction_factor * (pipe_length_m / pipe_diameter_m) * (density_kg_m3 * velocity_m_s**2 / 2)


def darcy_weisbach_pressure_loss_record(
    friction_factor: float,
    pipe_length_m: float,
    pipe_diameter_m: float,
    density_kg_m3: float,
    velocity_m_s: float,
) -> CalculationRecord:
    """Calculate Darcy-Weisbach pressure loss and return a reproducible record."""
    result = darcy_weisbach_pressure_loss(
        friction_factor,
        pipe_length_m,
        pipe_diameter_m,
        density_kg_m3,
        velocity_m_s,
    )
    return CalculationRecord(
        calculation_type=DARCY_MODEL.key,
        inputs={
            "friction_factor": friction_factor,
            "pipe_length": pipe_length_m,
            "pipe_diameter": pipe_diameter_m,
            "density": density_kg_m3,
            "velocity": velocity_m_s,
        },
        units={
            "friction_factor": "dimensionless",
            "pipe_length": "m",
            "pipe_diameter": "m",
            "density": "kg/m^3",
            "velocity": "m/s",
        },
        assumptions=DARCY_METHOD.assumptions,
        method=DARCY_METHOD.equation,
        result=result,
        result_unit="Pa",
        source="deterministic calculation",
        method_version=DARCY_METHOD.version,
    )
