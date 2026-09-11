from calculation_definitions import (
    DARCY_METHOD,
    DARCY_MODEL,
    HYDROSTATIC_METHOD,
    HYDROSTATIC_MODEL,
    HYDROSTATIC_PARAMETERS,
)
from calculation_library import (
    calculate as calculate_detailed,
    circular_pipe_area,
    darcy_weisbach_pressure_loss,
    dynamic_pressure,
    electrical_power,
    hydrostatic_pressure,
    ideal_gas_pressure,
    mechanical_power,
    normal_strain,
    normal_stress,
    ohms_law_voltage,
    pipe_velocity,
    pressure_from_head,
    pressure_head,
    reynolds_number,
    volumetric_flow,
)
from calculation_records import CalculationRecord


def hydrostatic_pressure_record(density_kg_m3: float, gravity_m_s2: float, depth_m: float) -> CalculationRecord:
    result = hydrostatic_pressure(density_kg_m3, gravity_m_s2, depth_m)
    return CalculationRecord(
        calculation_type=HYDROSTATIC_MODEL.key,
        inputs={"density": density_kg_m3, "gravity": gravity_m_s2, "depth": depth_m},
        units={parameter.name: parameter.default_unit or "" for parameter in HYDROSTATIC_PARAMETERS},
        assumptions=HYDROSTATIC_METHOD.assumptions,
        method=HYDROSTATIC_METHOD.equation,
        result=result,
        result_unit="Pa",
        source="deterministic calculation",
        method_version=HYDROSTATIC_METHOD.version,
    )


def darcy_weisbach_pressure_loss_record(
    friction_factor: float,
    pipe_length_m: float,
    pipe_diameter_m: float,
    density_kg_m3: float,
    velocity_m_s: float,
) -> CalculationRecord:
    result = darcy_weisbach_pressure_loss(
        friction_factor,
        pipe_length_m,
        pipe_diameter_m,
        density_kg_m3,
        velocity_m_s,
    )
    return CalculationRecord(
        calculation_type=DARCY_MODEL.key,
        inputs={
            "friction_factor": friction_factor,
            "pipe_length": pipe_length_m,
            "pipe_diameter": pipe_diameter_m,
            "density": density_kg_m3,
            "velocity": velocity_m_s,
        },
        units={
            "friction_factor": "dimensionless",
            "pipe_length": "m",
            "pipe_diameter": "m",
            "density": "kg/m^3",
            "velocity": "m/s",
        },
        assumptions=DARCY_METHOD.assumptions,
        method=DARCY_METHOD.equation,
        result=result,
        result_unit="Pa",
        source="deterministic calculation",
        method_version=DARCY_METHOD.version,
    )


__all__ = [
    "calculate_detailed",
    "circular_pipe_area",
    "darcy_weisbach_pressure_loss",
    "darcy_weisbach_pressure_loss_record",
    "dynamic_pressure",
    "electrical_power",
    "hydrostatic_pressure",
    "hydrostatic_pressure_record",
    "ideal_gas_pressure",
    "mechanical_power",
    "normal_strain",
    "normal_stress",
    "ohms_law_voltage",
    "pipe_velocity",
    "pressure_from_head",
    "pressure_head",
    "reynolds_number",
    "volumetric_flow",
]
