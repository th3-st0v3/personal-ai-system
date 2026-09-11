from calculation_library import SPECS
from calculation_models import CalculationModel, CalculationParameter, MethodVersion


def _parameters(model_key: str, spec_key: str) -> tuple[CalculationParameter, ...]:
    metadata = {
        "hydrostatic_pressure": (("density", "Fluid density.", "mass_per_volume", 0.0, None, "kg/m^3"), ("gravity", "Gravitational acceleration.", "length_per_time_squared", 0.0, None, "m/s^2"), ("depth", "Vertical fluid-column depth.", "length", 0.0, None, "m")),
        "darcy_weisbach_pressure_loss": (("friction_factor", "Darcy friction factor.", "dimensionless", 0.0, None, "dimensionless"), ("pipe_length", "Pipe length.", "length", 0.0, None, "m"), ("pipe_diameter", "Pipe internal diameter.", "length", 0.0, None, "m"), ("density", "Fluid density.", "mass_per_volume", 0.0, None, "kg/m^3"), ("velocity", "Mean fluid velocity.", "length_per_time", 0.0, None, "m/s")),
        "reynolds_number": (("density", "Fluid density.", "mass_per_volume", 0.0, None, "kg/m^3"), ("velocity", "Mean velocity.", "length_per_time", 0.0, None, "m/s"), ("diameter", "Hydraulic diameter.", "length", 0.0, None, "m"), ("dynamic_viscosity", "Dynamic viscosity.", "mass_per_length_time", 0.0, None, "Pa*s")),
        "volumetric_flow": (("area", "Flow cross-sectional area.", "area", 0.0, None, "m^2"), ("velocity", "Mean velocity.", "length_per_time", 0.0, None, "m/s")),
        "circular_pipe_area": (("diameter", "Circular diameter.", "length", 0.0, None, "m"),),
        "pipe_velocity": (("flow_rate", "Volumetric flow rate.", "volume_per_time", 0.0, None, "m^3/s"), ("diameter", "Pipe diameter.", "length", 0.0, None, "m")),
        "dynamic_pressure": (("density", "Fluid density.", "mass_per_volume", 0.0, None, "kg/m^3"), ("velocity", "Mean velocity.", "length_per_time", 0.0, None, "m/s")),
        "pressure_head": (("pressure", "Pressure.", "pressure", 0.0, None, "Pa"), ("density", "Fluid density.", "mass_per_volume", 0.0, None, "kg/m^3"), ("gravity", "Gravitational acceleration.", "length_per_time_squared", 0.0, None, "m/s^2")),
        "pressure_from_head": (("head", "Pressure head.", "length", 0.0, None, "m"), ("density", "Fluid density.", "mass_per_volume", 0.0, None, "kg/m^3"), ("gravity", "Gravitational acceleration.", "length_per_time_squared", 0.0, None, "m/s^2")),
        "ideal_gas_pressure": (("amount", "Amount of substance.", "amount_of_substance", 0.0, None, "mol"), ("temperature", "Absolute temperature.", "temperature", 0.0, None, "K"), ("volume", "Gas volume.", "volume", 0.0, None, "m^3"), ("gas_constant", "Universal gas constant.", "energy_per_amount_temperature", 0.0, None, "J/(mol*K)")),
        "normal_stress": (("force", "Normal load.", "force", 0.0, None, "N"), ("area", "Loaded area.", "area", 0.0, None, "m^2")),
        "normal_strain": (("delta_length", "Change in length.", "length", 0.0, None, "m"), ("original_length", "Original length.", "length", 0.0, None, "m")),
        "ohms_law_voltage": (("current", "Electrical current.", "current", 0.0, None, "A"), ("resistance", "Resistance.", "resistance", 0.0, None, "ohm")),
        "electrical_power": (("voltage", "Voltage.", "voltage", 0.0, None, "V"), ("current", "Current.", "current", 0.0, None, "A")),
        "mechanical_power": (("torque", "Torque.", "torque", 0.0, None, "N*m"), ("angular_velocity", "Angular velocity.", "angle_per_time", 0.0, None, "rad/s")),
    }
    return tuple(CalculationParameter(model_key, name, description, "number", True, dimension, minimum, maximum, unit) for name, description, dimension, minimum, maximum, unit in metadata[spec_key])


_DEFINITIONS = []
for spec in SPECS:
    model = CalculationModel(
        key=spec.key,
        name=spec.name,
        domain=spec.domain,
        description=f"Deterministic engineering calculation for {spec.name.lower()}.",
        model_type="deterministic_equation",
    )
    method = MethodVersion(
        calculation_model_key=model.key,
        version="1.0",
        equation=spec.equation,
        description=f"Calculates {spec.name.lower()} from the supplied inputs.",
        applicability="Use when the stated equation and assumptions are appropriate to the physical system.",
        assumptions=spec.assumptions,
        limitations=spec.limitations,
    )
    _DEFINITIONS.append((model, method, _parameters(model.key, spec.key)))

CALCULATION_DEFINITIONS = tuple(_DEFINITIONS)

# Stable names kept for existing callers/tests.
_H = next(item for item in CALCULATION_DEFINITIONS if item[0].key == "hydrostatic_pressure")
_D = next(item for item in CALCULATION_DEFINITIONS if item[0].key == "darcy_weisbach_pressure_loss")
HYDROSTATIC_MODEL, HYDROSTATIC_METHOD, HYDROSTATIC_PARAMETERS = _H
DARCY_MODEL, DARCY_METHOD, DARCY_PARAMETERS = _D
