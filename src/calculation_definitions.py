from calculation_models import CalculationModel, CalculationParameter, MethodVersion


def _model(key, name, domain, description):
    return CalculationModel(key=key, name=name, domain=domain, description=description, model_type="deterministic_equation")


def _method(model, version, equation, description, applicability, assumptions, limitations):
    return MethodVersion(
        calculation_model_key=model.key,
        version=version,
        equation=equation,
        description=description,
        applicability=applicability,
        assumptions=assumptions,
        limitations=limitations,
    )


def _p(model, name, description, dimension, minimum=0.0, maximum=None, unit=None):
    return CalculationParameter(model.key, name, description, "number", True, dimension, minimum, maximum, unit)


HYDROSTATIC_MODEL = _model("hydrostatic_pressure", "Hydrostatic Pressure", "fluid_pressure", "Pressure from a constant-density fluid column.")
HYDROSTATIC_METHOD = _method(
    HYDROSTATIC_MODEL, "1.0", "P = rho * g * h",
    "Calculates hydrostatic pressure from density, gravity, and vertical depth.",
    "Constant-density fluid column with constant gravitational acceleration.",
    ("constant density", "constant gravitational acceleration", "pressure reported as gauge pressure relative to the column reference"),
    ("Does not model pressure-dependent density.", "Does not include friction, acceleration, or multiphase effects."),
)
HYDROSTATIC_PARAMETERS = (
    _p(HYDROSTATIC_MODEL, "density", "Fluid density.", "mass_per_volume", unit="kg/m^3"),
    _p(HYDROSTATIC_MODEL, "gravity", "Gravitational acceleration.", "length_per_time_squared", unit="m/s^2"),
    _p(HYDROSTATIC_MODEL, "depth", "Vertical fluid-column depth.", "length", unit="m"),
)

DARCY_MODEL = _model("darcy_weisbach_pressure_loss", "Darcy-Weisbach Pressure Loss", "fluid_flow", "Frictional pressure loss for steady internal pipe flow.")
DARCY_METHOD = _method(
    DARCY_MODEL, "1.0", "DeltaP = f * (L / D) * (rho * v^2 / 2)",
    "Calculates frictional pressure loss using a supplied Darcy friction factor.",
    "Steady internal flow with a supplied Darcy friction factor.",
    ("constant density", "steady flow", "single effective pipe diameter"),
    ("Requires a valid supplied friction factor.", "Does not include fittings or elevation change."),
)
DARCY_PARAMETERS = (
    _p(DARCY_MODEL, "friction_factor", "Darcy friction factor.", "dimensionless", unit="dimensionless"),
    _p(DARCY_MODEL, "pipe_length", "Pipe length.", "length", unit="m"),
    _p(DARCY_MODEL, "pipe_diameter", "Pipe internal diameter.", "length", unit="m"),
    _p(DARCY_MODEL, "density", "Fluid density.", "mass_per_volume", unit="kg/m^3"),
    _p(DARCY_MODEL, "velocity", "Mean fluid velocity.", "length_per_time", unit="m/s"),
)

PIPE_AREA_MODEL = _model("pipe_cross_sectional_area", "Pipe Cross-Sectional Area", "fluid_geometry", "Internal circular flow area from pipe diameter.")
PIPE_AREA_METHOD = _method(PIPE_AREA_MODEL, "1.0", "A = pi * D^2 / 4", "Calculates the internal area of a circular pipe.", "Circular internal pipe geometry.", ("circular cross-section",), ("Does not account for eccentric or non-circular geometry."))
PIPE_AREA_PARAMETERS = (_p(PIPE_AREA_MODEL, "pipe_diameter", "Pipe internal diameter.", "length", unit="m"),)

FLOW_RATE_MODEL = _model("volumetric_flow_rate", "Volumetric Flow Rate", "fluid_flow", "Volumetric flow rate from mean velocity and circular pipe area.")
FLOW_RATE_METHOD = _method(FLOW_RATE_MODEL, "1.0", "Q = v * A = v * pi * D^2 / 4", "Calculates volumetric flow rate from velocity and pipe diameter.", "Steady mean velocity in a circular pipe.", ("mean velocity represents the flow cross-section", "circular pipe"), ("Does not model velocity profiles explicitly."))
FLOW_RATE_PARAMETERS = (
    _p(FLOW_RATE_MODEL, "velocity", "Mean fluid velocity.", "length_per_time", unit="m/s"),
    _p(FLOW_RATE_MODEL, "pipe_diameter", "Pipe internal diameter.", "length", unit="m"),
)

VELOCITY_MODEL = _model("fluid_velocity", "Fluid Velocity", "fluid_flow", "Mean fluid velocity from volumetric flow rate and circular pipe area.")
VELOCITY_METHOD = _method(VELOCITY_MODEL, "1.0", "v = Q / A = 4Q / (pi * D^2)", "Calculates mean velocity from volumetric flow rate and pipe diameter.", "Circular pipe flow using a cross-sectional mean velocity.", ("circular pipe",), ("Does not model local velocity distribution."))
VELOCITY_PARAMETERS = (
    _p(VELOCITY_MODEL, "flow_rate", "Volumetric flow rate.", "volume_per_time", unit="m^3/s"),
    _p(VELOCITY_MODEL, "pipe_diameter", "Pipe internal diameter.", "length", unit="m"),
)

REYNOLDS_MODEL = _model("reynolds_number", "Reynolds Number", "fluid_flow", "Dimensionless Reynolds number for internal pipe flow.")
REYNOLDS_METHOD = _method(REYNOLDS_MODEL, "1.0", "Re = rho * v * D / mu", "Calculates the Reynolds number from density, velocity, diameter, and dynamic viscosity.", "Newtonian fluid in a pipe with representative mean properties.", ("constant representative properties", "Newtonian viscosity"), ("Does not determine friction factor by itself.", "Non-Newtonian behavior requires a different rheological treatment."))
REYNOLDS_PARAMETERS = (
    _p(REYNOLDS_MODEL, "density", "Fluid density.", "mass_per_volume", unit="kg/m^3"),
    _p(REYNOLDS_MODEL, "velocity", "Mean fluid velocity.", "length_per_time", unit="m/s"),
    _p(REYNOLDS_MODEL, "pipe_diameter", "Pipe internal diameter.", "length", unit="m"),
    _p(REYNOLDS_MODEL, "dynamic_viscosity", "Dynamic viscosity.", "mass_per_length_time", minimum=0.000000001, unit="Pa*s"),
)

PRESSURE_GRADIENT_MODEL = _model("hydrostatic_pressure_gradient", "Hydrostatic Pressure Gradient", "fluid_pressure", "Pressure gradient from fluid density and gravity.")
PRESSURE_GRADIENT_METHOD = _method(PRESSURE_GRADIENT_MODEL, "1.0", "dP/dh = rho * g", "Calculates the hydrostatic pressure gradient per unit vertical depth.", "Constant-density fluid column.", ("constant density", "constant gravity"), ("Does not include dynamic pressure losses or formation-pressure effects."))
PRESSURE_GRADIENT_PARAMETERS = (
    _p(PRESSURE_GRADIENT_MODEL, "density", "Fluid density.", "mass_per_volume", unit="kg/m^3"),
    _p(PRESSURE_GRADIENT_MODEL, "gravity", "Gravitational acceleration.", "length_per_time_squared", unit="m/s^2"),
)

HYDRAULIC_POWER_MODEL = _model("hydraulic_power", "Hydraulic Power", "fluid_power", "Hydraulic power associated with a pressure drop and volumetric flow rate.")
HYDRAULIC_POWER_METHOD = _method(HYDRAULIC_POWER_MODEL, "1.0", "P = DeltaP * Q", "Calculates ideal hydraulic power from pressure differential and volumetric flow rate.", "Fluid power across a defined pressure differential.", ("pressure and flow rate refer to the same control volume", "ideal hydraulic power"), ("Does not include pump or motor efficiency."))
HYDRAULIC_POWER_PARAMETERS = (
    _p(HYDRAULIC_POWER_MODEL, "pressure_drop", "Pressure differential.", "pressure", unit="Pa"),
    _p(HYDRAULIC_POWER_MODEL, "flow_rate", "Volumetric flow rate.", "volume_per_time", unit="m^3/s"),
)

API_GRAVITY_MODEL = _model("api_gravity_to_specific_gravity", "API Gravity to Specific Gravity", "petroleum_fluids", "Converts API gravity at the petroleum reference condition to specific gravity.")
API_GRAVITY_METHOD = _method(API_GRAVITY_MODEL, "1.0", "SG = 141.5 / (API + 131.5)", "Converts API gravity to specific gravity using the standard petroleum relationship.", "Petroleum liquid API gravity referenced at the conventional 60 degF condition.", ("API gravity uses the standard petroleum reference condition",), ("Does not correct for temperature outside the reference condition.", "Does not model composition-dependent density behavior."))
API_GRAVITY_PARAMETERS = (_p(API_GRAVITY_MODEL, "api_gravity", "API gravity at the reference condition.", "dimensionless", minimum=-131.49, unit="deg API"),)

CALCULATION_DEFINITIONS = (
    (HYDROSTATIC_MODEL, HYDROSTATIC_METHOD, HYDROSTATIC_PARAMETERS),
    (DARCY_MODEL, DARCY_METHOD, DARCY_PARAMETERS),
    (PIPE_AREA_MODEL, PIPE_AREA_METHOD, PIPE_AREA_PARAMETERS),
    (FLOW_RATE_MODEL, FLOW_RATE_METHOD, FLOW_RATE_PARAMETERS),
    (VELOCITY_MODEL, VELOCITY_METHOD, VELOCITY_PARAMETERS),
    (REYNOLDS_MODEL, REYNOLDS_METHOD, REYNOLDS_PARAMETERS),
    (PRESSURE_GRADIENT_MODEL, PRESSURE_GRADIENT_METHOD, PRESSURE_GRADIENT_PARAMETERS),
    (HYDRAULIC_POWER_MODEL, HYDRAULIC_POWER_METHOD, HYDRAULIC_POWER_PARAMETERS),
    (API_GRAVITY_MODEL, API_GRAVITY_METHOD, API_GRAVITY_PARAMETERS),
)
