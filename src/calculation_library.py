"""Deterministic engineering calculations with auditable solution traces."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable


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

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready detailed trace for UI/API rendering."""
        return {
            "key": self.key,
            "name": self.name,
            "equation": self.equation,
            "inputs": dict(self.inputs),
            "substitutions": self.substitutions,
            "steps": list(self.steps),
            "result": self.result,
            "result_unit": self.result_unit,
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
        }


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


def _finite(name: str, value: float) -> None:
    if not math.isfinite(value): raise ValueError(f"{name} must be finite")

def _nonnegative(name: str, value: float) -> None:
    _finite(name, value)
    if value < 0: raise ValueError(f"{name} must be non-negative")

def _positive(name: str, value: float) -> None:
    _nonnegative(name, value)
    if value == 0: raise ValueError(f"{name} must be greater than zero")


def hydrostatic_pressure(density, gravity, depth):
    for name, value in (("density", density), ("gravity", gravity), ("depth", depth)): _nonnegative(name, value)
    return density * gravity * depth

def darcy_weisbach_pressure_loss(friction_factor, pipe_length, pipe_diameter, density, velocity):
    for name, value in (("friction factor", friction_factor), ("pipe length", pipe_length), ("density", density), ("velocity", velocity)): _nonnegative(name, value)
    _positive("pipe diameter", pipe_diameter); return friction_factor * (pipe_length / pipe_diameter) * (density * velocity**2 / 2)

def reynolds_number(density, velocity, diameter, dynamic_viscosity):
    _nonnegative("density", density); _nonnegative("velocity", velocity); _positive("diameter", diameter); _positive("dynamic_viscosity", dynamic_viscosity); return density * velocity * diameter / dynamic_viscosity

def volumetric_flow(area, velocity):
    _nonnegative("area", area); _nonnegative("velocity", velocity); return area * velocity

def circular_pipe_area(diameter):
    _positive("diameter", diameter); return math.pi * diameter**2 / 4

def pipe_velocity(flow_rate, diameter):
    _nonnegative("flow_rate", flow_rate); _positive("diameter", diameter); return flow_rate / circular_pipe_area(diameter)

def dynamic_pressure(density, velocity):
    _nonnegative("density", density); _nonnegative("velocity", velocity); return density * velocity**2 / 2

def pressure_head(pressure, density, gravity=9.80665):
    _nonnegative("pressure", pressure); _positive("density", density); _positive("gravity", gravity); return pressure / (density * gravity)

def pressure_from_head(head, density, gravity=9.80665):
    _nonnegative("head", head); _positive("density", density); _positive("gravity", gravity); return density * gravity * head

def bernoulli_pressure_downstream(pressure_upstream, velocity_upstream, velocity_downstream, elevation_upstream, elevation_downstream, density, gravity=9.80665, head_loss=0.0):
    for name, value in (("pressure_upstream", pressure_upstream), ("velocity_upstream", velocity_upstream), ("velocity_downstream", velocity_downstream), ("head_loss", head_loss)): _nonnegative(name, value)
    _finite("elevation_upstream", elevation_upstream); _finite("elevation_downstream", elevation_downstream); _positive("density", density); _positive("gravity", gravity)
    return pressure_upstream + density * gravity * (elevation_upstream - elevation_downstream - head_loss) + 0.5 * density * (velocity_upstream**2 - velocity_downstream**2)

def ideal_gas_pressure(amount, temperature, volume, gas_constant=8.314462618):
    _nonnegative("amount", amount); _positive("temperature", temperature); _positive("volume", volume); _positive("gas_constant", gas_constant); return amount * gas_constant * temperature / volume

def ideal_gas_density(molar_mass, pressure, temperature, gas_constant=8.314462618):
    _positive("molar_mass", molar_mass); _nonnegative("pressure", pressure); _positive("temperature", temperature); _positive("gas_constant", gas_constant); return pressure * molar_mass / (gas_constant * temperature)

def normal_stress(force, area):
    _nonnegative("force", force); _positive("area", area); return force / area

def normal_strain(delta_length, original_length):
    _nonnegative("delta_length", delta_length); _positive("original_length", original_length); return delta_length / original_length

def ohms_law_voltage(current, resistance):
    _nonnegative("current", current); _nonnegative("resistance", resistance); return current * resistance

def electrical_power(voltage, current):
    _nonnegative("voltage", voltage); _nonnegative("current", current); return voltage * current

def mechanical_power(torque, angular_velocity):
    _nonnegative("torque", torque); _nonnegative("angular_velocity", angular_velocity); return torque * angular_velocity

def kinetic_energy(mass, velocity):
    _nonnegative("mass", mass); _nonnegative("velocity", velocity); return 0.5 * mass * velocity**2

def gravitational_potential_energy(mass, gravity, height):
    _nonnegative("mass", mass); _nonnegative("gravity", gravity); _finite("height", height); return mass * gravity * height

def spring_force(stiffness, displacement):
    _nonnegative("stiffness", stiffness); _finite("displacement", displacement); return stiffness * displacement

def spring_potential_energy(stiffness, displacement):
    _nonnegative("stiffness", stiffness); _finite("displacement", displacement); return 0.5 * stiffness * displacement**2

def thermal_expansion(initial_length, coefficient, delta_temperature):
    _positive("initial_length", initial_length); _nonnegative("coefficient", coefficient); _finite("delta_temperature", delta_temperature); return initial_length * coefficient * delta_temperature

def sensible_heat(mass, specific_heat, delta_temperature):
    _nonnegative("mass", mass); _nonnegative("specific_heat", specific_heat); _finite("delta_temperature", delta_temperature); return mass * specific_heat * delta_temperature

def conduction_heat_rate(conductivity, area, delta_temperature, thickness):
    _nonnegative("conductivity", conductivity); _nonnegative("area", area); _finite("delta_temperature", delta_temperature); _positive("thickness", thickness); return conductivity * area * delta_temperature / thickness

def fluid_mass_flow(density, volumetric_flow_rate):
    _nonnegative("density", density); _nonnegative("volumetric_flow_rate", volumetric_flow_rate); return density * volumetric_flow_rate

def buoyancy_force(fluid_density, gravity, displaced_volume):
    _nonnegative("fluid_density", fluid_density); _nonnegative("gravity", gravity); _nonnegative("displaced_volume", displaced_volume); return fluid_density * gravity * displaced_volume

def efficiency(useful_output, total_input):
    _nonnegative("useful_output", useful_output); _positive("total_input", total_input)
    if useful_output > total_input: raise ValueError("useful_output cannot exceed total_input")
    return useful_output / total_input

def electrical_resistance_series(resistance_1, resistance_2):
    _nonnegative("resistance_1", resistance_1); _nonnegative("resistance_2", resistance_2); return resistance_1 + resistance_2

def electrical_resistance_parallel(resistance_1, resistance_2):
    _positive("resistance_1", resistance_1); _positive("resistance_2", resistance_2); return 1.0 / (1.0 / resistance_1 + 1.0 / resistance_2)

def capacitor_energy(capacitance, voltage):
    _nonnegative("capacitance", capacitance); _nonnegative("voltage", voltage); return 0.5 * capacitance * voltage**2

def rc_time_constant(resistance, capacitance):
    _nonnegative("resistance", resistance); _nonnegative("capacitance", capacitance); return resistance * capacitance


def _fmt(values, equation):
    return equation.format(**{key: f"{value:g}" for key, value in values.items()})


def _defaulted(values, key, default):
    return {**values, key: values.get(key, default)}


SPECS = (
    CalculationSpec("hydrostatic_pressure", "Hydrostatic Pressure", "fluid_pressure", "P = rho * g * h", "Pa", hydrostatic_pressure, lambda v: _fmt(v, "P = ({density})({gravity})({depth})"), ("constant density", "constant gravitational acceleration"), ("Does not model pressure-dependent density.",)),
    CalculationSpec("darcy_weisbach_pressure_loss", "Darcy-Weisbach Pressure Loss", "fluid_flow", "ΔP = f * (L / D) * (rho * v^2 / 2)", "Pa", darcy_weisbach_pressure_loss, lambda v: _fmt(v, "ΔP = ({friction_factor})({pipe_length}/{pipe_diameter})(({density})({velocity}^2)/2)"), ("steady internal flow", "constant density", "supplied Darcy friction factor"), ("Requires a valid supplied friction factor; does not calculate it.",)),
    CalculationSpec("reynolds_number", "Reynolds Number", "fluid_flow", "Re = rho * v * D / mu", "dimensionless", reynolds_number, lambda v: _fmt(v, "Re = ({density})({velocity})({diameter})/{dynamic_viscosity}"), ("Newtonian-fluid viscosity represented by supplied dynamic viscosity",), ("Flow-regime interpretation depends on geometry and assumptions.",)),
    CalculationSpec("volumetric_flow", "Volumetric Flow Rate", "fluid_flow", "Q = A * v", "m^3/s", volumetric_flow, lambda v: _fmt(v, "Q = ({area})({velocity})"), ("one-dimensional mean velocity through the stated area",), ("Does not model velocity-profile effects.",)),
    CalculationSpec("circular_pipe_area", "Circular Pipe Area", "geometry", "A = pi * D^2 / 4", "m^2", circular_pipe_area, lambda v: _fmt(v, "A = pi * ({diameter})^2 / 4"), ("circular cross-section",), ()),
    CalculationSpec("pipe_velocity", "Pipe Mean Velocity", "fluid_flow", "v = Q / A", "m/s", pipe_velocity, lambda v: _fmt(v, "v = {flow_rate} / (pi * {diameter}^2 / 4)"), ("circular pipe", "mean velocity"), ()),
    CalculationSpec("dynamic_pressure", "Dynamic Pressure", "fluid_pressure", "q = rho * v^2 / 2", "Pa", dynamic_pressure, lambda v: _fmt(v, "q = ({density})({velocity}^2)/2"), ("incompressible-flow form",), ("Compressibility may matter at high Mach number.",)),
    CalculationSpec("pressure_head", "Pressure Head", "fluid_pressure", "h = P / (rho * g)", "m", pressure_head, lambda v: _fmt(_defaulted(v, "gravity", 9.80665), "h = {pressure} / (({density})({gravity}))"), ("positive pressure and density",), ()),
    CalculationSpec("pressure_from_head", "Pressure From Head", "fluid_pressure", "P = rho * g * h", "Pa", pressure_from_head, lambda v: _fmt(_defaulted(v, "gravity", 9.80665), "P = ({density})({gravity})({head})"), ("constant density",), ()),
    CalculationSpec("bernoulli_pressure_downstream", "Bernoulli Downstream Pressure", "fluid_flow", "P2 = P1 + rho*g(z1-z2-hL) + rho(v1^2-v2^2)/2", "Pa", bernoulli_pressure_downstream, lambda v: _fmt(_defaulted(v, "gravity", 9.80665), "P2 = {pressure_upstream} + ({density})({gravity})({elevation_upstream}-{elevation_downstream}-{head_loss}) + ({density})({velocity_upstream}^2-{velocity_downstream}^2)/2"), ("steady incompressible flow", "consistent datum for elevations"), ("Does not account for pump/turbine work or compressibility beyond the supplied terms.",)),
    CalculationSpec("ideal_gas_pressure", "Ideal Gas Pressure", "thermodynamics", "P = nRT / V", "Pa", ideal_gas_pressure, lambda v: _fmt(_defaulted(v, "gas_constant", 8.314462618), "P = ({amount})({gas_constant})({temperature})/{volume}"), ("ideal-gas behavior", "absolute temperature"), ("Real-gas deviations are not modeled.",)),
    CalculationSpec("ideal_gas_density", "Ideal Gas Density", "thermodynamics", "rho = P*M / (R*T)", "kg/m^3", ideal_gas_density, lambda v: _fmt(_defaulted(v, "gas_constant", 8.314462618), "rho = ({pressure})({molar_mass})/(({gas_constant})({temperature}))"), ("ideal-gas behavior", "absolute temperature", "molar mass expressed in kg/mol"), ("Real-gas compressibility is not modeled.",)),
    CalculationSpec("normal_stress", "Normal Stress", "solid_mechanics", "sigma = F / A", "Pa", normal_stress, lambda v: _fmt(v, "sigma = {force} / {area}"), ("uniform load over stated area",), ("Does not resolve local stress concentrations.",)),
    CalculationSpec("normal_strain", "Normal Strain", "solid_mechanics", "epsilon = dL / L0", "dimensionless", normal_strain, lambda v: _fmt(v, "epsilon = {delta_length} / {original_length}"), ("engineering strain representation",), ()),
    CalculationSpec("ohms_law_voltage", "Ohm's Law Voltage", "electrical", "V = I * R", "V", ohms_law_voltage, lambda v: _fmt(v, "V = ({current})({resistance})"), ("linear resistance model",), ("Not valid for nonlinear devices without adjustment.",)),
    CalculationSpec("electrical_power", "Electrical Power", "electrical", "P = V * I", "W", electrical_power, lambda v: _fmt(v, "P = ({voltage})({current})"), ("DC or instantaneous real-power form",), ()),
    CalculationSpec("mechanical_power", "Mechanical Power", "mechanical", "P = tau * omega", "W", mechanical_power, lambda v: _fmt(v, "P = ({torque})({angular_velocity})"), ("rotational mechanical power",), ()),
    CalculationSpec("kinetic_energy", "Kinetic Energy", "mechanics", "E = m*v^2/2", "J", kinetic_energy, lambda v: _fmt(v, "E = ({mass})({velocity}^2)/2"), ("classical mechanics", "translational kinetic energy"), ("Relativistic effects are not modeled.",)),
    CalculationSpec("gravitational_potential_energy", "Gravitational Potential Energy", "mechanics", "E = m*g*h", "J", gravitational_potential_energy, lambda v: _fmt(v, "E = ({mass})({gravity})({height})"), ("uniform gravitational acceleration", "height measured from the chosen datum"), ("Does not model variation of gravity with altitude.",)),
    CalculationSpec("spring_force", "Linear Spring Force", "mechanics", "F = k*x", "N", spring_force, lambda v: _fmt(v, "F = ({stiffness})({displacement})"), ("linear elastic spring",), ("Nonlinear and hysteretic spring behavior is not modeled.",)),
    CalculationSpec("spring_potential_energy", "Spring Potential Energy", "mechanics", "E = k*x^2/2", "J", spring_potential_energy, lambda v: _fmt(v, "E = ({stiffness})({displacement}^2)/2"), ("linear elastic spring",), ("Energy losses are not modeled.",)),
    CalculationSpec("thermal_expansion", "Linear Thermal Expansion", "thermal", "ΔL = alpha*L0*ΔT", "m", thermal_expansion, lambda v: _fmt(v, "ΔL = ({coefficient})({initial_length})({delta_temperature})"), ("uniform isotropic linear expansion", "constant expansion coefficient"), ("Temperature-dependent material properties are not modeled.",)),
    CalculationSpec("sensible_heat", "Sensible Heat", "thermal", "Q = m*c*ΔT", "J", sensible_heat, lambda v: _fmt(v, "Q = ({mass})({specific_heat})({delta_temperature})"), ("constant specific heat",), ("Phase changes and temperature-dependent specific heat are not modeled.",)),
    CalculationSpec("conduction_heat_rate", "One-Dimensional Conduction Heat Rate", "heat_transfer", "Qdot = k*A*ΔT/L", "W", conduction_heat_rate, lambda v: _fmt(v, "Qdot = ({conductivity})({area})({delta_temperature})/{thickness}"), ("steady one-dimensional conduction", "constant thermal conductivity", "negligible contact resistance"), ("Multidimensional effects and convection/radiation are not included.",)),
    CalculationSpec("fluid_mass_flow", "Fluid Mass Flow Rate", "fluid_flow", "mdot = rho*Q", "kg/s", fluid_mass_flow, lambda v: _fmt(v, "mdot = ({density})({volumetric_flow_rate})"), ("density represented by supplied value",), ("Compressibility and transient density changes are not modeled.",)),
    CalculationSpec("buoyancy_force", "Buoyant Force", "fluid_statics", "Fb = rho*g*V", "N", buoyancy_force, lambda v: _fmt(v, "Fb = ({fluid_density})({gravity})({displaced_volume})"), ("uniform fluid density", "fully specified displaced volume"), ("Fluid free-surface and dynamic effects are not modeled.",)),
    CalculationSpec("efficiency", "Efficiency", "energy", "eta = useful_output / total_input", "dimensionless", efficiency, lambda v: _fmt(v, "eta = {useful_output} / {total_input}"), ("non-negative input and output quantities", "useful output cannot exceed total input"), ("Loss mechanisms are not resolved individually.",)),
    CalculationSpec("electrical_resistance_series", "Series Resistance", "electrical", "R = R1 + R2", "ohm", electrical_resistance_series, lambda v: _fmt(v, "R = {resistance_1} + {resistance_2}"), ("ideal series connection",), ("Parasitic effects are not modeled.",)),
    CalculationSpec("electrical_resistance_parallel", "Parallel Resistance", "electrical", "R = R1*R2/(R1+R2)", "ohm", electrical_resistance_parallel, lambda v: _fmt(v, "R = ({resistance_1})({resistance_2})/({resistance_1}+{resistance_2})"), ("ideal two-resistor parallel connection",), ("Parasitic effects are not modeled.",)),
    CalculationSpec("capacitor_energy", "Capacitor Stored Energy", "electrical", "E = C*V^2/2", "J", capacitor_energy, lambda v: _fmt(v, "E = ({capacitance})({voltage}^2)/2"), ("ideal capacitor",), ("Leakage and dielectric losses are not modeled.",)),
    CalculationSpec("rc_time_constant", "RC Time Constant", "electrical", "tau = R*C", "s", rc_time_constant, lambda v: _fmt(v, "tau = ({resistance})({capacitance})"), ("first-order ideal RC model",), ("Parasitic inductance and non-ideal component behavior are not modeled.",)),
)

CALCULATION_REGISTRY = {spec.key: spec for spec in SPECS}


def calculate(key: str, **inputs: float) -> CalculationTrace:
    try: spec = CALCULATION_REGISTRY[key]
    except KeyError as exc: raise ValueError(f"Unknown calculation '{key}'.") from exc
    result = spec.calculate(**inputs); substitution = spec.substitutions(inputs)
    steps = (
        f"Equation: {spec.equation}",
        "Validate supplied inputs as finite numeric values within the model's defined bounds.",
        f"Substitute values: {substitution}",
        f"Evaluate expression: {result:g} {spec.result_unit}",
        f"Report result: {spec.name} = {result:g} {spec.result_unit}",
        "Review the stated assumptions before using the result for an engineering decision.",
    )
    return CalculationTrace(spec.key, spec.name, spec.equation, dict(inputs), substitution, steps, result, spec.result_unit, spec.assumptions, spec.limitations)
