import math

from calculation_definitions import (
    API_GRAVITY_METHOD,
    API_GRAVITY_MODEL,
    API_GRAVITY_PARAMETERS,
    DARCY_METHOD,
    DARCY_MODEL,
    DARCY_PARAMETERS,
    FLOW_RATE_METHOD,
    FLOW_RATE_MODEL,
    FLOW_RATE_PARAMETERS,
    HYDRAULIC_POWER_METHOD,
    HYDRAULIC_POWER_MODEL,
    HYDRAULIC_POWER_PARAMETERS,
    HYDROSTATIC_METHOD,
    HYDROSTATIC_MODEL,
    HYDROSTATIC_PARAMETERS,
    PIPE_AREA_METHOD,
    PIPE_AREA_MODEL,
    PIPE_AREA_PARAMETERS,
    PRESSURE_GRADIENT_METHOD,
    PRESSURE_GRADIENT_MODEL,
    PRESSURE_GRADIENT_PARAMETERS,
    REYNOLDS_METHOD,
    REYNOLDS_MODEL,
    REYNOLDS_PARAMETERS,
    VELOCITY_METHOD,
    VELOCITY_MODEL,
    VELOCITY_PARAMETERS,
)
from calculation_records import CalculationRecord


def _validate_non_negative(name: str, value: float) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _record(model, method, parameters, inputs, result, result_unit):
    return CalculationRecord(
        calculation_type=model.key,
        inputs=inputs,
        units={parameter.name: parameter.default_unit or "" for parameter in parameters},
        assumptions=method.assumptions,
        method=method.equation,
        result=result,
        result_unit=result_unit,
        source="deterministic calculation",
        method_version=method.version,
    )


def hydrostatic_pressure(density_kg_m3, gravity_m_s2, depth_m):
    _validate_non_negative("density", density_kg_m3)
    _validate_non_negative("gravity", gravity_m_s2)
    _validate_non_negative("depth", depth_m)
    return density_kg_m3 * gravity_m_s2 * depth_m


def hydrostatic_pressure_record(density_kg_m3, gravity_m_s2, depth_m):
    result = hydrostatic_pressure(density_kg_m3, gravity_m_s2, depth_m)
    return _record(HYDROSTATIC_MODEL, HYDROSTATIC_METHOD, HYDROSTATIC_PARAMETERS,
                   {"density": density_kg_m3, "gravity": gravity_m_s2, "depth": depth_m}, result, "Pa")


def darcy_weisbach_pressure_loss(friction_factor, pipe_length_m, pipe_diameter_m, density_kg_m3, velocity_m_s):
    for name, value in (("friction factor", friction_factor), ("pipe length", pipe_length_m),
                        ("pipe diameter", pipe_diameter_m), ("density", density_kg_m3),
                        ("velocity", velocity_m_s)):
        _validate_non_negative(name, value)
    if pipe_diameter_m == 0:
        raise ValueError("pipe diameter must be greater than zero")
    return friction_factor * (pipe_length_m / pipe_diameter_m) * (density_kg_m3 * velocity_m_s**2 / 2)


def darcy_weisbach_pressure_loss_record(friction_factor, pipe_length_m, pipe_diameter_m, density_kg_m3, velocity_m_s):
    result = darcy_weisbach_pressure_loss(friction_factor, pipe_length_m, pipe_diameter_m, density_kg_m3, velocity_m_s)
    return _record(
        DARCY_MODEL, DARCY_METHOD, DARCY_PARAMETERS,
        {"friction_factor": friction_factor, "pipe_length": pipe_length_m,
         "pipe_diameter": pipe_diameter_m, "density": density_kg_m3, "velocity": velocity_m_s},
        result, "Pa",
    )


def pipe_cross_sectional_area(pipe_diameter_m):
    _validate_non_negative("pipe diameter", pipe_diameter_m)
    return math.pi * pipe_diameter_m**2 / 4


def pipe_cross_sectional_area_record(pipe_diameter_m):
    result = pipe_cross_sectional_area(pipe_diameter_m)
    return _record(PIPE_AREA_MODEL, PIPE_AREA_METHOD, PIPE_AREA_PARAMETERS,
                   {"pipe_diameter": pipe_diameter_m}, result, "m^2")


def volumetric_flow_rate(velocity_m_s, pipe_diameter_m):
    _validate_non_negative("velocity", velocity_m_s)
    return velocity_m_s * pipe_cross_sectional_area(pipe_diameter_m)


def volumetric_flow_rate_record(velocity_m_s, pipe_diameter_m):
    result = volumetric_flow_rate(velocity_m_s, pipe_diameter_m)
    return _record(FLOW_RATE_MODEL, FLOW_RATE_METHOD, FLOW_RATE_PARAMETERS,
                   {"velocity": velocity_m_s, "pipe_diameter": pipe_diameter_m}, result, "m^3/s")


def fluid_velocity(flow_rate_m3_s, pipe_diameter_m):
    _validate_non_negative("flow rate", flow_rate_m3_s)
    area = pipe_cross_sectional_area(pipe_diameter_m)
    if area == 0:
        raise ValueError("pipe diameter must be greater than zero")
    return flow_rate_m3_s / area


def fluid_velocity_record(flow_rate_m3_s, pipe_diameter_m):
    result = fluid_velocity(flow_rate_m3_s, pipe_diameter_m)
    return _record(VELOCITY_MODEL, VELOCITY_METHOD, VELOCITY_PARAMETERS,
                   {"flow_rate": flow_rate_m3_s, "pipe_diameter": pipe_diameter_m}, result, "m/s")


def reynolds_number(density_kg_m3, velocity_m_s, pipe_diameter_m, dynamic_viscosity_pa_s):
    for name, value in (("density", density_kg_m3), ("velocity", velocity_m_s), ("pipe diameter", pipe_diameter_m)):
        _validate_non_negative(name, value)
    if dynamic_viscosity_pa_s <= 0:
        raise ValueError("dynamic viscosity must be greater than zero")
    return density_kg_m3 * velocity_m_s * pipe_diameter_m / dynamic_viscosity_pa_s


def reynolds_number_record(density_kg_m3, velocity_m_s, pipe_diameter_m, dynamic_viscosity_pa_s):
    result = reynolds_number(density_kg_m3, velocity_m_s, pipe_diameter_m, dynamic_viscosity_pa_s)
    return _record(REYNOLDS_MODEL, REYNOLDS_METHOD, REYNOLDS_PARAMETERS,
                   {"density": density_kg_m3, "velocity": velocity_m_s,
                    "pipe_diameter": pipe_diameter_m, "dynamic_viscosity": dynamic_viscosity_pa_s}, result, "dimensionless")


def hydrostatic_pressure_gradient(density_kg_m3, gravity_m_s2):
    _validate_non_negative("density", density_kg_m3)
    _validate_non_negative("gravity", gravity_m_s2)
    return density_kg_m3 * gravity_m_s2


def hydrostatic_pressure_gradient_record(density_kg_m3, gravity_m_s2):
    result = hydrostatic_pressure_gradient(density_kg_m3, gravity_m_s2)
    return _record(PRESSURE_GRADIENT_MODEL, PRESSURE_GRADIENT_METHOD, PRESSURE_GRADIENT_PARAMETERS,
                   {"density": density_kg_m3, "gravity": gravity_m_s2}, result, "Pa/m")


def hydraulic_power(pressure_drop_pa, flow_rate_m3_s):
    _validate_non_negative("pressure drop", pressure_drop_pa)
    _validate_non_negative("flow rate", flow_rate_m3_s)
    return pressure_drop_pa * flow_rate_m3_s


def hydraulic_power_record(pressure_drop_pa, flow_rate_m3_s):
    result = hydraulic_power(pressure_drop_pa, flow_rate_m3_s)
    return _record(HYDRAULIC_POWER_MODEL, HYDRAULIC_POWER_METHOD, HYDRAULIC_POWER_PARAMETERS,
                   {"pressure_drop": pressure_drop_pa, "flow_rate": flow_rate_m3_s}, result, "W")


def api_gravity_to_specific_gravity(api_gravity):
    if api_gravity <= -131.5:
        raise ValueError("API gravity must be greater than -131.5")
    return 141.5 / (api_gravity + 131.5)


def api_gravity_to_specific_gravity_record(api_gravity):
    result = api_gravity_to_specific_gravity(api_gravity)
    return _record(API_GRAVITY_MODEL, API_GRAVITY_METHOD, API_GRAVITY_PARAMETERS,
                   {"api_gravity": api_gravity}, result, "dimensionless")
