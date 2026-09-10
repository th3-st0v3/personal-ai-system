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
