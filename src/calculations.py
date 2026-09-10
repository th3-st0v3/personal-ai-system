from calculation_records import CalculationRecord


def hydrostatic_pressure(
    density_kg_m3: float,
    gravity_m_s2: float,
    depth_m: float,
) -> float:
    """Calculate hydrostatic pressure: P = rho * g * h."""
    if density_kg_m3 < 0:
        raise ValueError("density must be non-negative")
    if gravity_m_s2 < 0:
        raise ValueError("gravity must be non-negative")
    if depth_m < 0:
        raise ValueError("depth must be non-negative")

    return density_kg_m3 * gravity_m_s2 * depth_m


def hydrostatic_pressure_record(
    density_kg_m3: float,
    gravity_m_s2: float,
    depth_m: float,
) -> CalculationRecord:
    """Calculate hydrostatic pressure and return a reproducible record."""
    result = hydrostatic_pressure(
        density_kg_m3,
        gravity_m_s2,
        depth_m,
    )

    return CalculationRecord(
        calculation_type="hydrostatic_pressure",
        inputs={
            "density": density_kg_m3,
            "gravity": gravity_m_s2,
            "depth": depth_m,
        },
        units={
            "density": "kg/m^3",
            "gravity": "m/s^2",
            "depth": "m",
        },
        assumptions=[
            "constant density",
            "constant gravitational acceleration",
        ],
        method="P = rho * g * h",
        result=result,
        result_unit="Pa",
        source="deterministic calculation",
    )
def darcy_weisbach_pressure_loss(
    friction_factor: float,
    pipe_length_m: float,
    pipe_diameter_m: float,
    density_kg_m3: float,
    velocity_m_s: float,
) -> float:
    """Calculate pressure loss using the Darcy-Weisbach equation."""
    if friction_factor < 0:
        raise ValueError("friction factor must be non-negative")
    if pipe_length_m < 0:
        raise ValueError("pipe length must be non-negative")
    if pipe_diameter_m < 0:
        raise ValueError("pipe diameter must be non-negative")
    if density_kg_m3 < 0:
        raise ValueError("density must be non-negative")
    if velocity_m_s < 0:
        raise ValueError("velocity must be non-negative")

    if pipe_diameter_m == 0:
        raise ValueError("pipe diameter must be greater than zero")

    return (
        friction_factor
        * (pipe_length_m / pipe_diameter_m)
        * (density_kg_m3 * velocity_m_s**2 / 2)
    )
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
        calculation_type="darcy_weisbach_pressure_loss",
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
        assumptions=[
            "constant density",
            "steady flow",
        ],
        method="ΔP = f * (L / D) * (rho * v^2 / 2)",
        result=result,
        result_unit="Pa",
        source="deterministic calculation",
    )
