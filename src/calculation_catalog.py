"""UX-facing catalog for the canonical deterministic calculation registry.

A calculation has one canonical implementation but may appear in multiple
engineering disciplines. The catalog therefore stores references, not copies.
"""
from __future__ import annotations

from dataclasses import dataclass

from calculation_library import CALCULATION_REGISTRY


@dataclass(frozen=True)
class CalculationCatalogEntry:
    key: str
    categories: tuple[str, ...]
    subcategories: tuple[str, ...]
    use_cases: tuple[str, ...]


CATALOG: tuple[CalculationCatalogEntry, ...] = (
    CalculationCatalogEntry("hydrostatic_pressure", ("Reservoir Engineering", "Drilling Engineering", "Production Engineering", "Fluid Mechanics"), ("Pressure", "Fluid Statics"), ("formation and wellbore pressure estimates", "hydrostatic column pressure", "pressure-depth relationships")),
    CalculationCatalogEntry("darcy_weisbach_pressure_loss", ("Drilling Engineering", "Production Engineering", "Fluid Mechanics"), ("Pressure Loss", "Pipe Flow"), ("circulating-system pressure loss", "pipe and tubular hydraulics", "flow-system sizing")),
    CalculationCatalogEntry("reynolds_number", ("Reservoir Engineering", "Drilling Engineering", "Production Engineering", "Fluid Mechanics"), ("Flow Regimes", "Dimensionless Numbers"), ("flow-regime assessment", "transport-model selection", "turbulence screening")),
    CalculationCatalogEntry("volumetric_flow", ("Reservoir Engineering", "Drilling Engineering", "Production Engineering", "Fluid Mechanics"), ("Flow Rate", "Pipe Flow"), ("rate calculations", "well and pipe flow", "surface-to-subsurface flow relationships")),
    CalculationCatalogEntry("circular_pipe_area", ("Drilling Engineering", "Production Engineering", "Fluid Mechanics"), ("Geometry", "Pipe Flow"), ("tubular flow area", "velocity-area relationships")),
    CalculationCatalogEntry("pipe_velocity", ("Drilling Engineering", "Production Engineering", "Fluid Mechanics"), ("Velocity", "Pipe Flow"), ("annular/pipe hydraulics foundations", "mean-flow calculations")),
    CalculationCatalogEntry("dynamic_pressure", ("Drilling Engineering", "Production Engineering", "Fluid Mechanics"), ("Pressure", "Flow Energy"), ("velocity-pressure relationships", "flow-system energy terms")),
    CalculationCatalogEntry("pressure_head", ("Reservoir Engineering", "Drilling Engineering", "Production Engineering", "Fluid Mechanics"), ("Pressure", "Head"), ("pressure-to-head conversion", "well and flow-system energy analysis")),
    CalculationCatalogEntry("pressure_from_head", ("Reservoir Engineering", "Drilling Engineering", "Production Engineering", "Fluid Mechanics"), ("Pressure", "Head"), ("head-to-pressure conversion", "well and flow-system energy analysis")),
    CalculationCatalogEntry("bernoulli_pressure_downstream", ("Reservoir Engineering", "Drilling Engineering", "Production Engineering", "Fluid Mechanics"), ("Pressure", "Energy Balance"), ("wellbore and flowline pressure prediction", "energy-grade analysis")),
    CalculationCatalogEntry("ideal_gas_pressure", ("Reservoir Engineering", "Drilling Engineering", "Thermodynamics"), ("Gas Properties", "Equation of State"), ("gas pressure estimation", "PVT foundations")),
    CalculationCatalogEntry("ideal_gas_density", ("Reservoir Engineering", "Drilling Engineering", "Thermodynamics"), ("Gas Properties", "Equation of State"), ("gas-density estimation", "gas-flow property calculations")),
    CalculationCatalogEntry("fluid_mass_flow", ("Reservoir Engineering", "Drilling Engineering", "Production Engineering", "Fluid Mechanics"), ("Flow Rate", "Mass Balance"), ("mass-rate conversion", "surface and subsurface flow accounting")),
    CalculationCatalogEntry("buoyancy_force", ("Drilling Engineering", "Well Completion Engineering", "Fluid Mechanics"), ("Fluid Statics", "Forces"), ("buoyancy checks", "submerged equipment and tubular analysis")),
    CalculationCatalogEntry("efficiency", ("Reservoir Engineering", "Drilling Engineering", "Production Engineering", "Mechanical Engineering", "Electrical Engineering"), ("Performance", "Energy"), ("system performance", "pump/motor/drive efficiency", "energy accounting")),
    CalculationCatalogEntry("normal_stress", ("Drilling Engineering", "Well Completion Engineering", "Mechanical Engineering"), ("Strength", "Solid Mechanics"), ("tubular loading", "component stress screening")),
    CalculationCatalogEntry("normal_strain", ("Drilling Engineering", "Well Completion Engineering", "Mechanical Engineering"), ("Deformation", "Solid Mechanics"), ("tubular deformation", "strain screening")),
    CalculationCatalogEntry("mechanical_power", ("Drilling Engineering", "Production Engineering", "Mechanical Engineering"), ("Power", "Rotating Equipment"), ("rotary systems", "pump and motor power relationships")),
    CalculationCatalogEntry("kinetic_energy", ("Drilling Engineering", "Production Engineering", "Mechanical Engineering"), ("Energy", "Mechanics"), ("moving-equipment energy estimates", "transient energy screening")),
    CalculationCatalogEntry("gravitational_potential_energy", ("Reservoir Engineering", "Drilling Engineering", "Production Engineering", "Mechanical Engineering"), ("Energy", "Mechanics"), ("elevation energy", "well and equipment energy balances")),
    CalculationCatalogEntry("spring_force", ("Well Completion Engineering", "Mechanical Engineering"), ("Forces", "Mechanics"), ("spring-loaded equipment", "mechanical force estimates")),
    CalculationCatalogEntry("spring_potential_energy", ("Well Completion Engineering", "Mechanical Engineering"), ("Energy", "Mechanics"), ("spring energy storage")),
    CalculationCatalogEntry("thermal_expansion", ("Drilling Engineering", "Well Completion Engineering", "Mechanical Engineering", "Thermodynamics"), ("Thermal Effects", "Material Response"), ("thermal tubular movement", "temperature-induced dimensional change")),
    CalculationCatalogEntry("sensible_heat", ("Reservoir Engineering", "Drilling Engineering", "Production Engineering", "Thermodynamics"), ("Heat", "Thermal Analysis"), ("fluid heating/cooling", "thermal energy accounting")),
    CalculationCatalogEntry("conduction_heat_rate", ("Drilling Engineering", "Well Completion Engineering", "Thermodynamics"), ("Heat Transfer", "Conduction"), ("thermal barriers", "heat-leak screening")),
    CalculationCatalogEntry("ohms_law_voltage", ("Electrical Engineering", "Instrumentation & Control"), ("Circuits", "DC Electrical"), ("voltage/current/resistance relationships")),
    CalculationCatalogEntry("electrical_power", ("Electrical Engineering", "Instrumentation & Control", "Production Engineering"), ("Power", "Circuits"), ("electrical load estimation", "instrument and equipment power")),
    CalculationCatalogEntry("electrical_resistance_series", ("Electrical Engineering", "Instrumentation & Control"), ("Circuits", "Resistance"), ("series circuit reduction")),
    CalculationCatalogEntry("electrical_resistance_parallel", ("Electrical Engineering", "Instrumentation & Control"), ("Circuits", "Resistance"), ("parallel circuit reduction")),
    CalculationCatalogEntry("capacitor_energy", ("Electrical Engineering", "Instrumentation & Control"), ("Circuits", "Energy Storage"), ("capacitive energy storage")),
    CalculationCatalogEntry("rc_time_constant", ("Electrical Engineering", "Instrumentation & Control"), ("Circuits", "Transient Response"), ("first-order response timing", "sensor and control dynamics")),
)

_ENTRY_BY_KEY = {entry.key: entry for entry in CATALOG}
_CATEGORY_ORDER = tuple(dict.fromkeys(category for entry in CATALOG for category in entry.categories))


def _entry(key: str) -> CalculationCatalogEntry:
    try:
        return _ENTRY_BY_KEY[key]
    except KeyError as exc:
        raise ValueError(f"Unknown calculation catalog entry: {key}") from exc


def get_entry(key: str) -> CalculationCatalogEntry:
    """Return the catalog metadata for one canonical calculation."""
    entry = _entry(key)
    if key not in CALCULATION_REGISTRY:
        raise RuntimeError(f"Catalog references unregistered calculation: {key}")
    return entry


def list_categories() -> tuple[str, ...]:
    """Return categories in intentional navigation order."""
    return _CATEGORY_ORDER


def list_category(category: str) -> tuple[str, ...]:
    """Return calculation keys belonging to a category, without duplicating implementations."""
    if category not in _CATEGORY_ORDER:
        raise ValueError(f"Unknown calculation category: {category}")
    return tuple(entry.key for entry in CATALOG if category in entry.categories)


def grouped_categories() -> dict[str, tuple[str, ...]]:
    """Return a frontend-ready category tree keyed by category name."""
    return {category: list_category(category) for category in _CATEGORY_ORDER}


def search(query: str, category: str | None = None) -> tuple[str, ...]:
    """Search names, keys, domains, equations, categories, and use cases."""
    normalized = " ".join(query.split()).casefold()
    if not normalized:
        raise ValueError("Search query is required.")
    if category is not None and category not in _CATEGORY_ORDER:
        raise ValueError(f"Unknown calculation category: {category}")
    terms = normalized.split()
    matches = []
    for entry in CATALOG:
        spec = CALCULATION_REGISTRY[entry.key]
        haystack = " ".join((spec.key, spec.name, spec.domain, spec.equation, *entry.categories, *entry.subcategories, *entry.use_cases)).casefold()
        if category is not None and category not in entry.categories:
            continue
        if all(term in haystack for term in terms):
            matches.append(entry.key)
    return tuple(matches)


__all__ = ["CATALOG", "CalculationCatalogEntry", "get_entry", "list_categories", "list_category", "grouped_categories", "search"]
