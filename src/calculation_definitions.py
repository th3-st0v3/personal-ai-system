from inspect import signature

from calculation_library import SPECS, CALCULATION_REGISTRY
from calculation_models import CalculationModel, CalculationParameter, MethodVersion


_PARAMETER_DATA = {
    "hydrostatic_pressure": (("density", "Fluid density.", "mass_per_volume", 0.0, None, "kg/m^3"), ("gravity", "Gravitational acceleration.", "length_per_time_squared", 0.0, None, "m/s^2"), ("depth", "Vertical fluid-column depth.", "length", 0.0, None, "m")),
    "darcy_weisbach_pressure_loss": (("friction_factor", "Darcy friction factor.", "dimensionless", 0.0, None, "dimensionless"), ("pipe_length", "Pipe length.", "length", 0.0, None, "m"), ("pipe_diameter", "Pipe internal diameter.", "length", 0.0, None, "m"), ("density", "Fluid density.", "mass_per_volume", 0.0, None, "kg/m^3"), ("velocity", "Mean fluid velocity.", "length_per_time", 0.0, None, "m/s")),
    "reynolds_number": (("density", "Fluid density.", "mass_per_volume", 0.0, None, "kg/m^3"), ("velocity", "Mean velocity.", "length_per_time", 0.0, None, "m/s"), ("diameter", "Hydraulic diameter.", "length", 0.0, None, "m"), ("dynamic_viscosity", "Dynamic viscosity.", "mass_per_length_time", 0.0, None, "Pa*s")),
    "volumetric_flow": (("area", "Flow cross-sectional area.", "area", 0.0, None, "m^2"), ("velocity", "Mean velocity.", "length_per_time", 0.0, None, "m/s")),
    "circular_pipe_area": (("diameter", "Circular diameter.", "length", 0.0, None, "m"),),
    "pipe_velocity": (("flow_rate", "Volumetric flow rate.", "volume_per_time", 0.0, None, "m^3/s"), ("diameter", "Pipe diameter.", "length", 0.0, None, "m")),
    "dynamic_pressure": (("density", "Fluid density.", "mass_per_volume", 0.0, None, "kg/m^3"), ("velocity", "Mean velocity.", "length_per_time", 0.0, None, "m/s")),
    "pressure_head": (("pressure", "Pressure.", "pressure", 0.0, None, "Pa"), ("density", "Fluid density.", "mass_per_volume", 0.0, None, "kg/m^3"), ("gravity", "Gravitational acceleration.", "length_per_time_squared", 0.0, None, "m/s^2")),
    "pressure_from_head": (("head", "Pressure head.", "length", 0.0, None, "m"), ("density", "Fluid density.", "mass_per_volume", 0.0, None, "kg/m^3"), ("gravity", "Gravitational acceleration.", "length_per_time_squared", 0.0, None, "m/s^2")),
    "bernoulli_pressure_downstream": (("pressure_upstream", "Upstream pressure.", "pressure", 0.0, None, "Pa"), ("velocity_upstream", "Upstream mean velocity.", "length_per_time", 0.0, None, "m/s"), ("velocity_downstream", "Downstream mean velocity.", "length_per_time", 0.0, None, "m/s"), ("elevation_upstream", "Upstream elevation relative to datum.", "length", None, None, "m"), ("elevation_downstream", "Downstream elevation relative to datum.", "length", None, None, "m"), ("density", "Fluid density.", "mass_per_volume", 0.0, None, "kg/m^3"), ("gravity", "Gravitational acceleration.", "length_per_time_squared", 0.0, None, "m/s^2"), ("head_loss", "Head loss between points.", "length", 0.0, None, "m")),
    "ideal_gas_pressure": (("amount", "Amount of substance.", "amount_of_substance", 0.0, None, "mol"), ("temperature", "Absolute temperature.", "temperature", 0.0, None, "K"), ("volume", "Gas volume.", "volume", 0.0, None, "m^3"), ("gas_constant", "Universal gas constant.", "energy_per_amount_temperature", 0.0, None, "J/(mol*K)")),
    "ideal_gas_density": (("molar_mass", "Gas molar mass.", "mass_per_amount", 0.0, None, "kg/mol"), ("pressure", "Absolute gas pressure.", "pressure", 0.0, None, "Pa"), ("temperature", "Absolute temperature.", "temperature", 0.0, None, "K"), ("gas_constant", "Universal gas constant.", "energy_per_amount_temperature", 0.0, None, "J/(mol*K)")),
    "normal_stress": (("force", "Normal load.", "force", 0.0, None, "N"), ("area", "Loaded area.", "area", 0.0, None, "m^2")),
    "normal_strain": (("delta_length", "Change in length.", "length", 0.0, None, "m"), ("original_length", "Original length.", "length", 0.0, None, "m")),
    "ohms_law_voltage": (("current", "Electrical current.", "current", 0.0, None, "A"), ("resistance", "Resistance.", "resistance", 0.0, None, "ohm")),
    "electrical_power": (("voltage", "Voltage.", "voltage", 0.0, None, "V"), ("current", "Current.", "current", 0.0, None, "A")),
    "mechanical_power": (("torque", "Torque.", "torque", 0.0, None, "N*m"), ("angular_velocity", "Angular velocity.", "angle_per_time", 0.0, None, "rad/s")),
    "kinetic_energy": (("mass", "Object mass.", "mass", 0.0, None, "kg"), ("velocity", "Object speed.", "length_per_time", 0.0, None, "m/s")),
    "gravitational_potential_energy": (("mass", "Object mass.", "mass", 0.0, None, "kg"), ("gravity", "Gravitational acceleration.", "length_per_time_squared", 0.0, None, "m/s^2"), ("height", "Height relative to datum.", "length", None, None, "m")),
    "spring_force": (("stiffness", "Linear spring stiffness.", "force_per_length", 0.0, None, "N/m"), ("displacement", "Spring displacement.", "length", None, None, "m")),
    "spring_potential_energy": (("stiffness", "Linear spring stiffness.", "force_per_length", 0.0, None, "N/m"), ("displacement", "Spring displacement.", "length", None, None, "m")),
    "thermal_expansion": (("initial_length", "Initial length.", "length", 0.0, None, "m"), ("coefficient", "Linear expansion coefficient.", "inverse_temperature", 0.0, None, "1/K"), ("delta_temperature", "Temperature change.", "temperature", None, None, "K")),
    "sensible_heat": (("mass", "Material mass.", "mass", 0.0, None, "kg"), ("specific_heat", "Specific heat capacity.", "energy_per_mass_temperature", 0.0, None, "J/(kg*K)"), ("delta_temperature", "Temperature change.", "temperature", None, None, "K")),
    "conduction_heat_rate": (("conductivity", "Thermal conductivity.", "power_per_length_temperature", 0.0, None, "W/(m*K)"), ("area", "Conduction area.", "area", 0.0, None, "m^2"), ("delta_temperature", "Temperature difference.", "temperature", None, None, "K"), ("thickness", "Conduction thickness.", "length", 0.0, None, "m")),
    "fluid_mass_flow": (("density", "Fluid density.", "mass_per_volume", 0.0, None, "kg/m^3"), ("volumetric_flow_rate", "Volumetric flow rate.", "volume_per_time", 0.0, None, "m^3/s")),
    "buoyancy_force": (("fluid_density", "Fluid density.", "mass_per_volume", 0.0, None, "kg/m^3"), ("gravity", "Gravitational acceleration.", "length_per_time_squared", 0.0, None, "m/s^2"), ("displaced_volume", "Displaced fluid volume.", "volume", 0.0, None, "m^3")),
    "efficiency": (("useful_output", "Useful output energy or power.", "energy", 0.0, None, "J"), ("total_input", "Total input energy or power.", "energy", 0.0, None, "J")),
    "electrical_resistance_series": (("resistance_1", "First series resistance.", "resistance", 0.0, None, "ohm"), ("resistance_2", "Second series resistance.", "resistance", 0.0, None, "ohm")),
    "electrical_resistance_parallel": (("resistance_1", "First parallel resistance.", "resistance", 0.0, None, "ohm"), ("resistance_2", "Second parallel resistance.", "resistance", 0.0, None, "ohm")),
    "capacitor_energy": (("capacitance", "Capacitance.", "capacitance", 0.0, None, "F"), ("voltage", "Capacitor voltage.", "voltage", 0.0, None, "V")),
    "rc_time_constant": (("resistance", "Resistance.", "resistance", 0.0, None, "ohm"), ("capacitance", "Capacitance.", "capacitance", 0.0, None, "F")),
    "annular_area": (("outer_diameter", "Outer annulus diameter.", "length", 0.0, None, "m"), ("inner_diameter", "Inner annulus diameter.", "length", 0.0, None, "m")),
    "annular_velocity": (("flow_rate", "Volumetric flow rate through annulus.", "volume_per_time", 0.0, None, "m^3/s"), ("outer_diameter", "Outer annulus diameter.", "length", 0.0, None, "m"), ("inner_diameter", "Inner annulus diameter.", "length", 0.0, None, "m")),
    "hydraulic_power": (("pressure_drop", "Pressure drop.", "pressure", 0.0, None, "Pa"), ("volumetric_flow_rate", "Volumetric flow rate.", "volume_per_time", 0.0, None, "m^3/s")),
    "equivalent_circulating_density": (("density", "Base drilling-fluid density.", "mass_per_volume", 0.0, None, "kg/m^3"), ("annular_pressure_loss", "Annular circulating pressure loss.", "pressure", 0.0, None, "Pa"), ("true_vertical_depth", "True vertical depth.", "length", 0.0, None, "m"), ("gravity", "Gravitational acceleration.", "length_per_time_squared", 0.0, None, "m/s^2")),
    "porosity": (("pore_volume", "Pore volume.", "volume", 0.0, None, "m^3"), ("bulk_volume", "Bulk rock volume.", "volume", 0.0, None, "m^3")),
    "water_saturation": (("water_volume", "Water-filled pore volume.", "volume", 0.0, None, "m^3"), ("pore_volume", "Total pore volume.", "volume", 0.0, None, "m^3")),
    "formation_volume_factor": (("reservoir_volume", "Fluid volume at reservoir conditions.", "volume", 0.0, None, "m^3"), ("standard_volume", "Equivalent fluid volume at standard conditions.", "volume", 0.0, None, "m^3")),
    "productivity_index": (("flow_rate", "Production flow rate.", "volume_per_time", 0.0, None, "m^3/s"), ("average_reservoir_pressure", "Average reservoir pressure.", "pressure", None, None, "Pa"), ("flowing_bottomhole_pressure", "Flowing bottomhole pressure.", "pressure", None, None, "Pa")),
    "radial_reservoir_flow_rate": (("permeability", "Reservoir permeability.", "area", 0.0, None, "m^2"), ("thickness", "Net reservoir thickness.", "length", 0.0, None, "m"), ("pressure_outer", "Pressure at outer radial boundary.", "pressure", None, None, "Pa"), ("pressure_well", "Pressure at wellbore.", "pressure", None, None, "Pa"), ("viscosity", "Fluid viscosity.", "dynamic_viscosity", 0.0, None, "Pa*s"), ("formation_volume_factor", "Formation volume factor.", "dimensionless", 0.0, None, "dimensionless"), ("outer_radius", "Outer radial boundary radius.", "length", 0.0, None, "m"), ("wellbore_radius", "Wellbore radius.", "length", 0.0, None, "m"), ("skin", "Dimensionless skin factor.", "dimensionless", None, None, "dimensionless")),
}


def _parameters(model_key: str, spec_key: str) -> tuple[CalculationParameter, ...]:
    return tuple(CalculationParameter(model_key, name, description, "number", True, dimension, minimum, maximum, unit) for name, description, dimension, minimum, maximum, unit in _PARAMETER_DATA[spec_key])


CALCULATION_DEFINITIONS = tuple(
    (
        CalculationModel(spec.key, spec.name, spec.domain, f"Deterministic engineering calculation for {spec.name.lower()}.", "deterministic_equation"),
        MethodVersion(spec.key, "1.0", spec.equation, f"Calculates {spec.name.lower()} from the supplied inputs.", "Use when the stated equation and assumptions are appropriate to the physical system.", spec.assumptions, spec.limitations),
        _parameters(spec.key, spec.key),
    )
    for spec in SPECS
)


def validate_definitions() -> None:
    """Raise if executable specs and UI/application metadata drift apart."""
    spec_keys = set(CALCULATION_REGISTRY)
    definition_keys = {model.key for model, _, _ in CALCULATION_DEFINITIONS}
    if spec_keys != definition_keys or definition_keys != set(_PARAMETER_DATA):
        raise RuntimeError("Calculation registry and definitions are out of sync.")
    for spec, (model, method, parameters) in zip(SPECS, CALCULATION_DEFINITIONS):
        if (model.key, method.calculation_model_key) != (spec.key, spec.key) or method.equation != spec.equation:
            raise RuntimeError(f"Calculation metadata drift for '{spec.key}'.")
        expected = tuple(signature(spec.calculate).parameters)
        actual = tuple(parameter.name for parameter in parameters)
        if expected != actual:
            raise RuntimeError(f"Calculation parameters drift for '{spec.key}': expected {expected}, got {actual}.")


_H = next(item for item in CALCULATION_DEFINITIONS if item[0].key == "hydrostatic_pressure")
_D = next(item for item in CALCULATION_DEFINITIONS if item[0].key == "darcy_weisbach_pressure_loss")
HYDROSTATIC_MODEL, HYDROSTATIC_METHOD, HYDROSTATIC_PARAMETERS = _H
DARCY_MODEL, DARCY_METHOD, DARCY_PARAMETERS = _D

validate_definitions()
