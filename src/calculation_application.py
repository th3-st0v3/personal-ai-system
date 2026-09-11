"""Application boundary for deterministic engineering calculations.

This module provides one stable entry point for selecting a registered
calculation model, validating its inputs, and executing the existing
specialized deterministic implementation. It keeps future UI/API/AI callers
from depending on individual calculation functions.
"""

import math

import calculations
from calculation_definitions import CALCULATION_DEFINITIONS
from calculation_models import CalculationModel, CalculationParameter, MethodVersion
from calculation_records import CalculationRecord


class CalculationApplication:
    """Run registered deterministic calculation models through one interface."""

    _EXECUTORS = {
        "hydrostatic_pressure": calculations.hydrostatic_pressure_record,
        "darcy_weisbach_pressure_loss": calculations.darcy_weisbach_pressure_loss_record,
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
        """Return registered calculation models in definition order."""
        return [definition[0] for definition in self._definitions.values()]

    def get_model(self, model_key: str) -> CalculationModel:
        """Return a model definition or raise for an unknown model key."""
        definition = self._definitions.get(model_key)
        if definition is None:
            raise ValueError(f"Unknown calculation model: {model_key}")
        return definition[0]

    def get_method(self, model_key: str) -> MethodVersion:
        """Return the current registered method version for a model."""
        definition = self._definitions.get(model_key)
        if definition is None:
            raise ValueError(f"Unknown calculation model: {model_key}")
        return definition[1]

    def get_parameters(self, model_key: str) -> tuple[CalculationParameter, ...]:
        """Return the registered input definitions for a model."""
        definition = self._definitions.get(model_key)
        if definition is None:
            raise ValueError(f"Unknown calculation model: {model_key}")
        return definition[2]

    def run(self, model_key: str, inputs: dict[str, float]) -> CalculationRecord:
        """Validate inputs and execute one deterministic calculation model."""
        definition = self._definitions.get(model_key)
        if definition is None:
            raise ValueError(f"Unknown calculation model: {model_key}")

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

        return self._EXECUTORS[model_key](**self._executor_arguments(model_key, validated))

    @staticmethod
    def _executor_arguments(model_key: str, inputs: dict[str, float]) -> dict[str, float]:
        if model_key == "hydrostatic_pressure":
            return {
                "density_kg_m3": inputs["density"],
                "gravity_m_s2": inputs["gravity"],
                "depth_m": inputs["depth"],
            }
        if model_key == "darcy_weisbach_pressure_loss":
            return {
                "friction_factor": inputs["friction_factor"],
                "pipe_length_m": inputs["pipe_length"],
                "pipe_diameter_m": inputs["pipe_diameter"],
                "density_kg_m3": inputs["density"],
                "velocity_m_s": inputs["velocity"],
            }
        raise ValueError(f"Unknown calculation model: {model_key}")


__all__ = ["CalculationApplication"]
