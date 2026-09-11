"""Application boundary for deterministic engineering calculations."""

import math

import calculations
import db
from calculation_definitions import CALCULATION_DEFINITIONS
from calculation_explanations import explain
from calculation_models import CalculationModel, CalculationParameter, MethodVersion
from calculation_records import CalculationRecord


class CalculationApplication:
    """Run registered deterministic calculation models through one interface."""

    _EXECUTORS = {
        "hydrostatic_pressure": calculations.hydrostatic_pressure_record,
        "darcy_weisbach_pressure_loss": calculations.darcy_weisbach_pressure_loss_record,
        "pipe_cross_sectional_area": calculations.pipe_cross_sectional_area_record,
        "volumetric_flow_rate": calculations.volumetric_flow_rate_record,
        "fluid_velocity": calculations.fluid_velocity_record,
        "reynolds_number": calculations.reynolds_number_record,
        "hydrostatic_pressure_gradient": calculations.hydrostatic_pressure_gradient_record,
        "hydraulic_power": calculations.hydraulic_power_record,
        "api_gravity_to_specific_gravity": calculations.api_gravity_to_specific_gravity_record,
    }

    def __init__(self):
        self._definitions = {
            model.key: (model, method, parameters)
            for model, method, parameters in CALCULATION_DEFINITIONS
        }
        unknown_executors = set(self._definitions) - set(self._EXECUTORS)
        if unknown_executors:
            raise RuntimeError(
                "No deterministic executor is registered for: "
                + ", ".join(sorted(unknown_executors))
            )

    def list_models(self) -> list[CalculationModel]:
        return [definition[0] for definition in self._definitions.values()]

    def get_model(self, model_key: str) -> CalculationModel:
        definition = self._definitions.get(model_key)
        if definition is None:
            raise ValueError(f"Unknown calculation model: {model_key}")
        return definition[0]

    def get_method(self, model_key: str) -> MethodVersion:
        definition = self._definitions.get(model_key)
        if definition is None:
            raise ValueError(f"Unknown calculation model: {model_key}")
        return definition[1]

    def get_parameters(self, model_key: str) -> tuple[CalculationParameter, ...]:
        definition = self._definitions.get(model_key)
        if definition is None:
            raise ValueError(f"Unknown calculation model: {model_key}")
        return definition[2]

    def run(self, model_key: str, inputs: dict[str, float]) -> CalculationRecord:
        validated = self._validate_inputs(model_key, inputs)
        return self._EXECUTORS[model_key](**self._executor_arguments(model_key, validated))

    def explain(self, model_key: str, inputs: dict[str, float]) -> dict:
        """Return the deterministic calculation plus its engineering explanation."""
        validated = self._validate_inputs(model_key, inputs)
        record = self._EXECUTORS[model_key](**self._executor_arguments(model_key, validated))
        method = self.get_method(model_key)
        details = explain(model_key, validated, record.result)
        return {
            "model": self.get_model(model_key),
            "method": method,
            "record": record,
            "steps": details["steps"],
            "interpretation": details["interpretation"],
        }

    def run_and_save(self, model_key: str, inputs: dict[str, float]) -> tuple[int, CalculationRecord]:
        record = self.run(model_key, inputs)
        calculation_id = db.save_calculation_record(record)
        return calculation_id, record

    def _validate_inputs(self, model_key: str, inputs: dict[str, float]) -> dict[str, float]:
        definition = self._definitions.get(model_key)
        if definition is None:
            raise ValueError(f"Unknown calculation model: {model_key}")
        if not isinstance(inputs, dict):
            raise ValueError("inputs must be a dictionary.")

        _, _, parameters = definition
        expected = {parameter.name: parameter for parameter in parameters}
        supplied = set(inputs)
        missing = [name for name, parameter in expected.items() if parameter.required and name not in supplied]
        unknown = supplied - set(expected)
        if missing:
            raise ValueError("Missing required inputs: " + ", ".join(missing))
        if unknown:
            raise ValueError("Unknown inputs: " + ", ".join(sorted(unknown)))

        validated = {}
        for name, value in inputs.items():
            parameter = expected[name]
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{name} must be a number.")
            numeric_value = float(value)
            if not math.isfinite(numeric_value):
                raise ValueError(f"{name} must be finite.")
            if parameter.minimum is not None and numeric_value < parameter.minimum:
                raise ValueError(f"{name} must be at least {parameter.minimum}.")
            if parameter.maximum is not None and numeric_value > parameter.maximum:
                raise ValueError(f"{name} must be at most {parameter.maximum}.")
            validated[name] = numeric_value
        return validated

    @staticmethod
    def _executor_arguments(model_key: str, inputs: dict[str, float]) -> dict[str, float]:
        mappings = {
            "hydrostatic_pressure": {"density_kg_m3": "density", "gravity_m_s2": "gravity", "depth_m": "depth"},
            "darcy_weisbach_pressure_loss": {"friction_factor": "friction_factor", "pipe_length_m": "pipe_length", "pipe_diameter_m": "pipe_diameter", "density_kg_m3": "density", "velocity_m_s": "velocity"},
            "pipe_cross_sectional_area": {"pipe_diameter_m": "pipe_diameter"},
            "volumetric_flow_rate": {"velocity_m_s": "velocity", "pipe_diameter_m": "pipe_diameter"},
            "fluid_velocity": {"flow_rate_m3_s": "flow_rate", "pipe_diameter_m": "pipe_diameter"},
            "reynolds_number": {"density_kg_m3": "density", "velocity_m_s": "velocity", "pipe_diameter_m": "pipe_diameter", "dynamic_viscosity_pa_s": "dynamic_viscosity"},
            "hydrostatic_pressure_gradient": {"density_kg_m3": "density", "gravity_m_s2": "gravity"},
            "hydraulic_power": {"pressure_drop_pa": "pressure_drop", "flow_rate_m3_s": "flow_rate"},
            "api_gravity_to_specific_gravity": {"api_gravity": "api_gravity"},
        }
        mapping = mappings.get(model_key)
        if mapping is None:
            raise ValueError(f"Unknown calculation model: {model_key}")
        return {executor_name: inputs[input_name] for executor_name, input_name in mapping.items()}


__all__ = ["CalculationApplication"]
