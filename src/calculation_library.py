"""Deterministic engineering calculations with auditable step-by-step traces.

The registry is intentionally ordinary Python: no model is required to obtain
correct numerical results. Each operation validates inputs, computes a result,
and can expose the equation, substitutions, intermediate values, assumptions,
and limitations needed by a UI or evidence workflow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class CalculationTrace:
    key: str
    name: str
    equation: str
    inputs: dict[str, float]
    substitutions: str
    steps: tuple[str, ...]
    result: float
    result_unit: str
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class CalculationSpec:
    key: str
    name: str
    domain: str
    equation: str
    result_unit: str
    calculate: Callable[..., float]
    substitutions: Callable[[dict[str, float]], str]
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]


def _nonnegative(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _positive(name: str, value: float) -> None:
    _nonnegative(name, value)
    if value == 0:
        raise ValueError(f"{name} must be greater than zero")


def hydrostatic_pressure(density: float, gravity: float, depth: float) -> float:
    _nonnegative("density", density); _nonnegative("gravity", gravity); _nonnegative("depth", depth)
    return density * gravity * depth


def darcy_weisbach_pressure_loss(friction_factor: float, pipe_length: float, pipe_diameter: float, density: float, velocity: float) -> float:
    for name, value in (("friction_factor", friction_factor), ("pipe_length", pipe_length), ("density", density), ("velocity", velocity)):
        _nonnegative(name, value)
    _positive("pipe_diameter", pipe_diameter)
    return friction_factor * (pipe_length / pipe_diameter) * (density * velocity**2 / 2)


def reynolds_number(density: float, velocity: float, diameter: float, dynamic_viscosity: float) -> float:
    _nonnegative("density", density); _nonnegative("velocity", velocity); _positive("diameter", diameter); _positive("dynamic_viscosity", dynamic_viscosity)
    return density * velocity * diameter / dynamic_viscosity


def volumetric_flow(area: float, velocity: float) -> float:
    _nonnegative("area", area); _nonnegative("velocity", velocity)
    return area * velocity


def circular_pipe_area(diameter: float) -> float:
    _positive("diameter", diameter)
    return math.pi * diameter**2 / 4


def pipe_velocity(flow_rate: float, diameter: float) -> float:
    _nonnegative("flow_rate", flow_rate); _positive("diameter", diameter)
    return flow_rate / circular_pipe_area(diameter)


def dynamic_pressure(density: float, velocity: float) -> float:
    _nonnegative("density", density); _nonnegative("velocity", velocity)
    return density * velocity**2 / 2


def pressure_head(pressure: float, density: float, gravity: float = 9.80665) -> float:
    _nonnegative("pressure", pressure); _positive("density", density); _positive("gravity", gravity)
    return pressure / (density * gravity)


def pressure_from_head(head: float, density: float, gravity: float = 9.80665) -> float:
    _nonnegative("head", head); _positive("density", density); _positive("gravity", gravity)
    return density * gravity * head


def bernoulli_pressure_downstream(pressure_upstream: float, velocity_upstream: float, velocity_downstream: float, elevation_upstream: float, elevation_downstream: float, density: float, gravity: float = 9.80665, head_loss: float = 0.0) -> float:
    for name, value in (("pressure_upstream", pressure_upstream), ("velocity_upstream", velocity_upstream), ("velocity_downstream", velocity_downstream), ("elevation_upstream", elevation_upstream), ("elevation_downstream", elevation_downstream), ("head_loss", head_loss)):
        _nonnegative(name, value)
    _positive("density", density); _positive("gravity", gravity)
    return pressure_upstream + density * gravity * (elevation_upstream - elevation_downstream - head_loss) + 0.5 * density * (velocity_upstream**2 - velocity_downstream**2)


def ideal_gas_pressure(amount: float, temperature: float, volume: float, gas_constant: float = 8.314462618) -> float:
    _nonnegative("amount", amount); _positive("temperature", temperature); _positive("volume", volume); _positive("gas_constant", gas_constant)
    return amount * gas_constant * temperature / volume


def normal_stress(force: float, area: float) -> float:
    _nonnegative("force", force); _positive("area", area)
    return force / area


def normal_strain(delta_length: float, original_length: float) -> float:
    _nonnegative("delta_length", delta_length); _positive("original_length", original_length)
    return delta_length / original_length


def ohms_law_voltage(current: float, resistance: float) -> float:
    _nonnegative("current", current); _nonnegative("resistance", resistance)
    return current * resistance


def electrical_power(voltage: float, current: float) -> float:
    _nonnegative("voltage", voltage); _nonnegative("current", current)
    return voltage * current


def mechanical_power(torque: float, angular_velocity: float) -> float:
    _nonnegative("torque", torque); _nonnegative("angular_velocity", angular_velocity)
    return torque * angular_velocity


def _linear_substitution(values: dict[str, float]) -> str:
    return ", ".join(f"{key} = {value:g}" for key, value in values.items())


SPECS = (
    CalculationSpec("hydrostatic_pressure", "Hydrostatic Pressure", "fluid_pressure", "P = rho * g * h", "Pa", hydrostatic_pressure, lambda v: f"P = ({v['density']:g})({v['gravity']:g})({v['depth']:g})", ("constant density", "constant gravitational acceleration"), ("does not model pressure-dependent density",)),
    CalculationSpec("darcy_weisbach_pressure_loss", "Darcy-Weisbach Pressure Loss", "fluid_flow", "ΔP = f * (L / D) * (rho * v² / 2)", "Pa", darcy_weisbach_pressure_loss, lambda v: f"ΔP = ({v['friction_factor']:g})({v['pipe_length']:g}/{v['pipe_diameter']:g})(({v['density']:g})({v['velocity']:g}²)/2)", ("steady internal flow", "constant density", "supplied Darcy friction factor"), ("does not calculate friction factor",)),
    CalculationSpec("reynolds_number", "Reynolds Number", "fluid_flow", "Re = rho * v * D / mu", "dimensionless", reynolds_number, lambda v: f"Re = ({v['density']:g})({v['velocity']:g})({v['diameter']:g})/{v['dynamic_viscosity']:g}", ("Newtonian-fluid viscosity represented by supplied dynamic viscosity",), ("flow-regime interpretation requires appropriate geometry and assumptions",)),
    CalculationSpec("volumetric_flow", "Volumetric Flow Rate", "fluid_flow", "Q = A * v", "m^3/s", volumetric_flow, lambda v: f"Q = ({v['area']:g})({v['velocity']:g})", ("one-dimensional mean velocity through the stated area",), ("does not model velocity profile effects",)),
    CalculationSpec("circular_pipe_area", "Circular Pipe Area", "geometry", "A = pi * D² / 4", "m^2", circular_pipe_area, lambda v: f"A = pi * ({v['diameter']:g})² / 4", ("circular cross-section",), (),
    ),
    CalculationSpec("pipe_velocity", "Pipe Mean Velocity", "fluid_flow", "v = Q / A", "m/s", pipe_velocity, lambda v: f"v = {v['flow_rate']:g} / (pi * {v['diameter']:g}² / 4)", ("circular pipe", "mean velocity",), ()),
    CalculationSpec("dynamic_pressure", "Dynamic Pressure", "fluid_pressure", "q = rho * v² / 2", "Pa", dynamic_pressure, lambda v: f"q = ({v['density']:g})({v['velocity']:g}²)/2", ("incompressible-flow form",), ("compressibility may matter at high Mach number",)),
    CalculationSpec("pressure_head", "Pressure Head", "fluid_pressure", "h = P / (rho * g)", "m", pressure_head, lambda v: f"h = {v['pressure']:g} / (({v['density']:g})({v['gravity']:g}))", ("positive pressure and density",), ()),
    CalculationSpec("pressure_from_head", "Pressure From Head", "fluid_pressure", "P = rho * g * h", "Pa", pressure_from_head, lambda v: f"P = ({v['density']:g})({v['gravity']:g})({v['head']:g})", ("constant density",), ()),
    CalculationSpec("ideal_gas_pressure", "Ideal Gas Pressure", "thermodynamics", "P = nRT / V", "Pa", ideal_gas_pressure, lambda v: f"P = ({v['amount']:g})({v['gas_constant']:g})({v['temperature']:g})/{v['volume']:g}", ("ideal-gas behavior", "absolute temperature",), ("real-gas deviations are not modeled",)),
    CalculationSpec("normal_stress", "Normal Stress", "solid_mechanics", "σ = F / A", "Pa", normal_stress, lambda v: f"σ = {v['force']:g} / {v['area']:g}", ("uniform load over stated area",), ("does not resolve local stress concentrations",)),
    CalculationSpec("normal_strain", "Normal Strain", "solid_mechanics", "ε = ΔL / L₀", "dimensionless", normal_strain, lambda v: f"ε = {v['delta_length']:g} / {v['original_length']:g}", ("small-displacement engineering strain representation",), ()),
    CalculationSpec("ohms_law_voltage", "Ohm's Law Voltage", "electrical", "V = I * R", "V", ohms_law_voltage, lambda v: f"V = ({v['current']:g})({v['resistance']:g})", ("linear resistance model",), ("not valid for nonlinear devices without adjustment",)),
    CalculationSpec("electrical_power", "Electrical Power", "electrical", "P = V * I", "W", electrical_power, lambda v: f"P = ({v['voltage']:g})({v['current']:g})", ("DC or instantaneous real-power form",), ()),
    CalculationSpec("mechanical_power", "Mechanical Power", "mechanical", "P = tau * omega", "W", mechanical_power, lambda v: f"P = ({v['torque']:g})({v['angular_velocity']:g})", ("rotational mechanical power",), ()),
)

CALCULATION_REGISTRY = {spec.key: spec for spec in SPECS}


def calculate(key: str, **inputs: float) -> CalculationTrace:
    try:
        spec = CALCULATION_REGISTRY[key]
    except KeyError as exc:
        raise ValueError(f"Unknown calculation '{key}'.") from exc
    result = spec.calculate(**inputs)
    substitution = spec.substitutions(inputs)
    steps = (
        f"Equation: {spec.equation}",
        f"Substitute values: {substitution}",
        f"Evaluate expression: {result:g} {spec.result_unit}",
    )
    return CalculationTrace(spec.key, spec.name, spec.equation, dict(inputs), substitution, steps, result, spec.result_unit, spec.assumptions, spec.limitations)
