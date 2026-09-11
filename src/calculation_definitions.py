from calculation_library import SPECS
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
    "normal_stress": (("force", "Normal load.", "force", 0.0, None, "N"), ("area", "Loaded area.", "area", 0.0, None, "m^2")),
    "normal_strain": (("delta_length", "Change in length.", "length", 0.0, None, "m"), ("original_length", "Original length.", "length", 0.0, None, "m")),
    "ohms_law_voltage": (("current", "Electrical current.", "current", 0.0, None, "A"), ("resistance", "Resistance.", "resistance", 0.0, None, "ohm")),
    "electrical_power": (("voltage", "Voltage.", "voltage", 0.0, None, "V"), ("current", "Current.", "current", 0.0, None, "A")),
    "mechanical_power": (("torque", "Torque.", "torque", 0.0, None, "N*m"), ("angular_velocity", "Angular velocity.", "angle_per_time", 0.0, None, "rad/s")),
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

_H = next(item for item in CALCULATION_DEFINITIONS if item[0].key == "hydrostatic_pressure")
_D = next(item for item in CALCULATION_DEFINITIONS if item[0].key == "darcy_weisbach_pressure_loss")
HYDROSTATIC_MODEL, HYDROSTATIC_METHOD, HYDROSTATIC_PARAMETERS = _H
DARCY_MODEL, DARCY_METHOD, DARCY_PARAMETERS = _D
