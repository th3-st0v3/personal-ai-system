"""Application boundary for deterministic engineering calculations."""

import math

import calculations
import db
from calculation_catalog import get_entry, grouped_categories, list_category, list_categories, search
from calculation_definitions import CALCULATION_DEFINITIONS
from calculation_library import CalculationTrace
from calculation_models import CalculationModel, CalculationParameter, MethodVersion
from calculation_records import CalculationRecord


class CalculationApplication:
    """Run registered deterministic calculation models through one interface."""

    def __init__(self):
        self._definitions = {model.key: (model, method, parameters) for model, method, parameters in CALCULATION_DEFINITIONS}

    def list_models(self) -> list[CalculationModel]:
        """Return registered calculation models in definition order."""
        return [definition[0] for definition in self._definitions.values()]

    def list_categories(self) -> tuple[str, ...]:
        """Return the navigation categories used by the calculation catalog."""
        return list_categories()

    def list_category(self, category: str) -> tuple[str, ...]:
        """Return canonical calculation keys for one discipline/category."""
        return list_category(category)

    def grouped_categories(self) -> dict[str, tuple[str, ...]]:
        """Return the complete category tree for a frontend catalog."""
        return grouped_categories()

    def search(self, query: str, category: str | None = None) -> tuple[str, ...]:
        """Search the calculation catalog, optionally constrained to a category."""
        return search(query, category=category)

    def get_catalog_entry(self, model_key: str):
        """Return discipline and use-case metadata for a calculation."""
        self.get_model(model_key)
        return get_entry(model_key)

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

    def _validated_inputs(self, model_key: str, inputs: dict[str, float]) -> tuple[MethodVersion, tuple[CalculationParameter, ...], dict[str, float]]:
        definition = self._definitions.get(model_key)
        if definition is None:
            raise ValueError(f"Unknown calculation model: {model_key}")
        if not isinstance(inputs, dict):
            raise ValueError("inputs must be a dictionary.")

        _, method, parameters = definition
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
        return method, parameters, validated

    def run_trace(self, model_key: str, inputs: dict[str, float]) -> CalculationTrace:
        """Validate and execute a model, retaining the full auditable solution trace."""
        _, _, validated = self._validated_inputs(model_key, inputs)
        return calculations.calculate_detailed(model_key, **validated)

    def run(self, model_key: str, inputs: dict[str, float]) -> CalculationRecord:
        """Validate inputs and execute any registered deterministic model."""
        trace = self.run_trace(model_key, inputs)
        method = self.get_method(model_key)
        parameters = self.get_parameters(model_key)
        return CalculationRecord(
            calculation_type=trace.key,
            inputs=trace.inputs,
            units={parameter.name: parameter.default_unit or "" for parameter in parameters},
            assumptions=trace.assumptions,
            method=trace.equation,
            result=trace.result,
            result_unit=trace.result_unit,
            source="deterministic calculation library",
            method_version=method.version,
        )

    def run_and_save(self, model_key: str, inputs: dict[str, float]) -> tuple[int, CalculationRecord]:
        """Execute a deterministic calculation and persist its reproducible record."""
        record = self.run(model_key, inputs)
        calculation_id = db.save_calculation_record(record)
        return calculation_id, record


__all__ = ["CalculationApplication"]
