"""Navigation metadata for engineering calculator landing pages.

Each calculator remains implemented once in the canonical registry; majors only
reference the keys relevant to their workflows.
"""
from __future__ import annotations

from calculation_catalog import CATALOG


MAJOR_CALCULATION_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Petroleum Engineering", "Reservoir, drilling, production, and wellbore analysis.", ("Reservoir Engineering", "Drilling Engineering", "Production Engineering", "Petrophysics", "Well Completion Engineering")),
    ("Mechanical Engineering", "Mechanics, thermal systems, energy, and rotating equipment.", ("Mechanical Engineering", "Thermodynamics", "Thermal")),
    ("Electrical Engineering", "Circuits, power, resistance, storage, and instrumentation.", ("Electrical Engineering", "Instrumentation & Control")),
    ("Chemical Engineering", "Thermodynamics, transport, heat transfer, and process-oriented analysis.", ("Thermodynamics", "Fluid Mechanics", "Heat Transfer")),
    ("Civil Engineering", "Fluid systems, mechanics, and infrastructure-oriented fundamentals.", ("Fluid Mechanics", "Mechanical Engineering")),
    ("General Engineering", "Cross-discipline mechanics, energy, fluid, and geometry foundations.", ("Fluid Mechanics", "Mechanics", "Energy", "Geometry")),
)


def majors() -> tuple[dict[str, object], ...]:
    return tuple({"name": name, "description": description, "calculations": tuple(entry.key for entry in CATALOG if any(category in groups for category in entry.categories))} for name, description, groups in MAJOR_CALCULATION_GROUPS)


def major(name: str) -> dict[str, object]:
    for item in majors():
        if item["name"] == name:
            return item
    raise ValueError(f"Unknown engineering major: {name}")


__all__=["MAJOR_CALCULATION_GROUPS","majors","major"]
