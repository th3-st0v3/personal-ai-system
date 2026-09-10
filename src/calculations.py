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
