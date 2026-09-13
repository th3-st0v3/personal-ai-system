"""Six umbrella engineering groups for calculator navigation.

The calculator registry stays canonical; this module only determines how the
shared calculators are presented to users. Every requested engineering major
is represented exactly once inside an umbrella group.
"""
from __future__ import annotations

from typing import TypedDict

from calculation_catalog import CATALOG


class MajorGroup(TypedDict):
    name: str
    description: str
    includes: tuple[str, ...]
    calculations: tuple[str, ...]


MAJOR_CALCULATION_GROUPS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("Mechanical Engineering", "Mechanics, thermal systems, energy, rotating equipment, and related design work.", ("Mechanical Engineering", "Aerospace Engineering", "Automotive Engineering", "Electromechanical Engineering", "Manufacturing Engineering", "Mechatronics Engineering", "Robotics Engineering"), ("Mechanical Engineering", "Thermodynamics", "Thermal", "Mechanics", "Energy", "Geometry", "Fluid Mechanics", "Solid Mechanics")),
    ("Electrical & Computer Engineering", "Electrical systems, computing, communications, optics, electronics, and embedded systems.", ("Computer Engineering", "Electrical Engineering", "Photonics Engineering", "Optical Engineering", "Software Engineering", "Telecommunications Engineering"), ("Electrical Engineering", "Instrumentation & Control", "Circuits", "Power")),
    ("Chemical & Biological Engineering", "Chemical processes, bioengineering, materials, polymers, thermal systems, and transport.", ("Biochemical Engineering", "Bioengineering", "Biological Systems Engineering", "Biomedical Engineering", "Ceramics Engineering", "Chemical Engineering", "Materials Science and Engineering", "Metallurgical Engineering", "Plastics Engineering"), ("Thermodynamics", "Fluid Mechanics", "Heat Transfer", "Thermal", "Energy", "Electrical Engineering")),
    ("Civil & Environmental Engineering", "Structures, buildings, infrastructure, geospatial systems, transportation, and environmental systems.", ("Architectural Engineering", "Civil Engineering", "Construction Engineering", "Environmental Engineering", "Fire Protection Engineering", "Geomatics Engineering", "Geotechnical Engineering", "Structural Engineering", "Transportation Engineering"), ("Civil Engineering", "Fluid Mechanics", "Mechanical Engineering", "Geometry", "Mechanics", "Solid Mechanics", "Energy", "Thermodynamics")),
    ("Energy & Earth Resources Engineering", "Subsurface, energy, marine, mining, nuclear, petroleum, reservoir, and wind-energy systems.", ("Mining Engineering", "Nuclear Engineering", "Ocean Engineering", "Petroleum Engineering", "Marine Engineering", "Wind Energy Engineering"), ("Reservoir Engineering", "Production Engineering", "Drilling Engineering", "Petrophysics", "Well Completion Engineering", "Fluid Mechanics", "Thermodynamics", "Energy", "Mechanical Engineering")),
    ("Applied Sciences & Management", "Cross-disciplinary engineering science, operations, systems, agriculture, and engineering management.", ("Engineering Management", "Engineering Physics", "Industrial Engineering", "Nanotechnology Engineering", "Systems Engineering", "Agricultural Engineering"), ("Mechanical Engineering", "Electrical Engineering", "Thermodynamics", "Fluid Mechanics", "Mechanics", "Energy", "Geometry", "Electrical Engineering")),
)


def _calc_keys(categories: tuple[str, ...]) -> tuple[str, ...]:
    keys: list[str] = []
    seen: set[str] = set()
    for entry in CATALOG:
        if any(category in categories for category in entry.categories) and entry.key not in seen:
            keys.append(entry.key)
            seen.add(entry.key)
    return tuple(keys)


def majors() -> tuple[MajorGroup, ...]:
    return tuple(MajorGroup(name=name, description=description, includes=members, calculations=_calc_keys(categories)) for name, description, members, categories in MAJOR_CALCULATION_GROUPS)


def major(name: str) -> MajorGroup:
    for item in majors():
        if item["name"] == name:
            return item
    raise ValueError(f"Unknown engineering major: {name}")


__all__ = ["MajorGroup", "MAJOR_CALCULATION_GROUPS", "majors", "major"]
