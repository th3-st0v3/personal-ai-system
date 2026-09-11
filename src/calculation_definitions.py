from calculation_models import CalculationModel, CalculationParameter, MethodVersion

HYDROSTATIC_MODEL = CalculationModel(
    key="hydrostatic_pressure",
    name="Hydrostatic Pressure",
    domain="fluid_pressure",
    description="Pressure change from a constant-density fluid column.",
    model_type="deterministic_equation",
)

HYDROSTATIC_METHOD = MethodVersion(
    calculation_model_key=HYDROSTATIC_MODEL.key,
    version="1.0",
    equation="P = rho * g * h",
    description="Calculates hydrostatic pressure from density, gravity, and depth.",
    applicability="Constant-density fluid column with constant gravitational acceleration.",
    assumptions=("constant density", "constant gravitational acceleration"),
    limitations=("Does not model pressure-dependent density or fluid-property variation.",),
)

HYDROSTATIC_PARAMETERS = (
    CalculationParameter(HYDROSTATIC_MODEL.key, "density", "Fluid density.", "number", True, "mass_per_volume", 0.0, None, "kg/m^3"),
    CalculationParameter(HYDROSTATIC_MODEL.key, "gravity", "Gravitational acceleration.", "number", True, "length_per_time_squared", 0.0, None, "m/s^2"),
    CalculationParameter(HYDROSTATIC_MODEL.key, "depth", "Vertical fluid-column depth.", "number", True, "length", 0.0, None, "m"),
)

DARCY_MODEL = CalculationModel(
    key="darcy_weisbach_pressure_loss",
    name="Darcy-Weisbach Pressure Loss",
    domain="fluid_flow",
    description="Pressure loss for steady internal flow using the Darcy-Weisbach equation.",
    model_type="deterministic_equation",
)

DARCY_METHOD = MethodVersion(
    calculation_model_key=DARCY_MODEL.key,
    version="1.0",
    equation="ΔP = f * (L / D) * (rho * v^2 / 2)",
    description="Calculates frictional pressure loss in a pipe.",
    applicability="Steady internal flow with a supplied Darcy friction factor.",
    assumptions=("constant density", "steady flow"),
    limitations=("Requires a valid supplied friction factor; does not calculate it.",),
)

DARCY_PARAMETERS = (
    CalculationParameter(DARCY_MODEL.key, "friction_factor", "Darcy friction factor.", "number", True, "dimensionless", 0.0, None, "dimensionless"),
    CalculationParameter(DARCY_MODEL.key, "pipe_length", "Pipe length.", "number", True, "length", 0.0, None, "m"),
    CalculationParameter(DARCY_MODEL.key, "pipe_diameter", "Pipe internal diameter.", "number", True, "length", 0.0, None, "m"),
    CalculationParameter(DARCY_MODEL.key, "density", "Fluid density.", "number", True, "mass_per_volume", 0.0, None, "kg/m^3"),
    CalculationParameter(DARCY_MODEL.key, "velocity", "Mean fluid velocity.", "number", True, "length_per_time", 0.0, None, "m/s"),
)

CALCULATION_DEFINITIONS = (
    (HYDROSTATIC_MODEL, HYDROSTATIC_METHOD, HYDROSTATIC_PARAMETERS),
    (DARCY_MODEL, DARCY_METHOD, DARCY_PARAMETERS),
)
