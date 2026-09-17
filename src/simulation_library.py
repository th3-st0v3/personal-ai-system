"""Small deterministic engineering simulations for the beta workspace.

These are intentionally inspectable: every simulator returns inputs, derived
steps, outputs, assumptions, limitations, and reproducibility metadata instead
of a black-box number.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Callable, Mapping


SIMULATION_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class Simulation:
    key: str
    name: str
    discipline: str
    description: str
    parameters: tuple[str, ...]
    run: Callable[[dict[str, float]], dict[str, object]]


def _require(values: Mapping[str, float], *names: str) -> None:
    missing = [name for name in names if name not in values]
    if missing:
        raise ValueError(f"Missing simulation inputs: {', '.join(missing)}")
    if any(not math.isfinite(float(values[name])) for name in names):
        raise ValueError("Simulation inputs must be finite numbers.")


def _require_positive(values: Mapping[str, float], *names: str) -> None:
    _require(values, *names)
    invalid = [name for name in names if float(values[name]) <= 0]
    if invalid:
        raise ValueError(
            f"Simulation inputs must be positive: {', '.join(invalid)}"
        )


def _wellbore_hydraulics(v: dict[str, float]) -> dict[str, object]:
    _require_positive(v, "depth", "density", "diameter", "velocity", "viscosity")
    g = 9.80665
    reynolds = v["density"] * v["velocity"] * v["diameter"] / v["viscosity"]
    if reynolds <= 0:
        raise ValueError("Reynolds number must be positive.")
    friction = 64.0 / reynolds if reynolds < 2300 else 0.3164 / reynolds**0.25
    hydrostatic = v["density"] * g * v["depth"]
    dynamic = 0.5 * v["density"] * v["velocity"] ** 2
    loss = friction * (v["depth"] / v["diameter"]) * dynamic
    return {
        "outputs": {
            "hydrostatic_pressure": hydrostatic,
            "frictional_pressure_loss": loss,
            "bottom_pressure": hydrostatic + loss,
            "reynolds_number": reynolds,
            "friction_factor": friction,
        },
        "units": {
            "hydrostatic_pressure": "Pa",
            "frictional_pressure_loss": "Pa",
            "bottom_pressure": "Pa",
            "reynolds_number": "1",
            "friction_factor": "1",
        },
        "steps": [
            f"Re = {reynolds:.6g}",
            f"f = {friction:.6g}",
            f"P_h = rho*g*depth = {hydrostatic:.6g} Pa",
            f"DeltaP_f = f*(L/D)*(rho*v^2/2) = {loss:.6g} Pa",
            f"P_bottom = {hydrostatic + loss:.6g} Pa",
        ],
        "assumptions": [
            "Constant fluid properties",
            "Smooth-pipe Darcy friction approximation",
            "Acceleration and elevation changes other than depth are neglected",
        ],
        "limitations": [
            "Not a multiphase wellbore model",
            "Does not model temperature-dependent properties or pump/compressor behavior",
        ],
    }


def _heat_conduction(v: dict[str, float]) -> dict[str, object]:
    _require_positive(v, "conductivity", "area", "thickness")
    _require(v, "hot_temperature", "cold_temperature")
    delta_t = v["hot_temperature"] - v["cold_temperature"]
    resistance = v["thickness"] / (v["conductivity"] * v["area"])
    heat_rate = delta_t / resistance
    return {
        "outputs": {
            "heat_rate": heat_rate,
            "thermal_resistance": resistance,
            "temperature_difference": delta_t,
        },
        "units": {
            "heat_rate": "W",
            "thermal_resistance": "K/W",
            "temperature_difference": "K",
        },
        "steps": [
            f"DeltaT = Th-Tc = {delta_t:.6g} K",
            f"R = L/(k*A) = {resistance:.6g} K/W",
            f"Qdot = DeltaT/R = {heat_rate:.6g} W",
        ],
        "assumptions": [
            "One-dimensional steady conduction",
            "Constant thermal conductivity",
            "No internal heat generation",
        ],
        "limitations": [
            "Does not model convection/contact resistance unless represented by inputs"
        ],
    }


SIMULATIONS = (
    Simulation(
        "wellbore_hydraulics",
        "Wellbore hydraulics",
        "Petroleum Engineering",
        "Pressure profile using hydrostatic and Darcy-style friction terms.",
        ("depth", "density", "diameter", "velocity", "viscosity"),
        _wellbore_hydraulics,
    ),
    Simulation(
        "heat_conduction",
        "Heat conduction",
        "Mechanical / Chemical Engineering",
        "Steady one-dimensional conduction through a slab or wall.",
        ("conductivity", "area", "hot_temperature", "cold_temperature", "thickness"),
        _heat_conduction,
    ),
)
_INDEX = {simulation.key: simulation for simulation in SIMULATIONS}


def list_simulations() -> list[Simulation]:
    return list(SIMULATIONS)


def get_simulation(key: str) -> Simulation:
    try:
        return _INDEX[key]
    except KeyError as exc:
        raise ValueError(f"Unknown simulation '{key}'.") from exc


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def run_simulation(key: str, inputs: dict[str, float]) -> dict[str, object]:
    simulation = get_simulation(key)
    values = {str(name): float(value) for name, value in inputs.items()}
    result = simulation.run(values)
    outputs = result["outputs"]
    provenance = {
        "schema_version": SIMULATION_SCHEMA_VERSION,
        "simulation_key": simulation.key,
        "inputs": values,
        "assumptions": result["assumptions"],
        "limitations": result["limitations"],
        "output_fingerprint": _fingerprint(outputs),
    }
    provenance["fingerprint"] = _fingerprint(provenance)
    return {
        "schema_version": SIMULATION_SCHEMA_VERSION,
        "key": simulation.key,
        "name": simulation.name,
        "discipline": simulation.discipline,
        "inputs": values,
        "provenance": provenance,
        **result,
    }


__all__ = [
    "SIMULATION_SCHEMA_VERSION",
    "Simulation",
    "list_simulations",
    "get_simulation",
    "run_simulation",
]
