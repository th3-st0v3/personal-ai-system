"""Application boundary for deterministic engineering calculations."""

import hashlib
import inspect
import json
import math
from collections.abc import Mapping
from datetime import datetime, timezone

import calculations
import db
from calculation_catalog import get_entry, grouped_categories, list_category, list_categories, list_items, search
from calculation_definitions import CALCULATION_DEFINITIONS
from calculation_library import CALCULATION_REGISTRY, CalculationTrace
from calculation_models import CalculationModel, CalculationParameter, MethodVersion
from calculation_records import CalculationRecord
from calculation_trace_detail import expand_trace
from engineering_runtime import ExecutionPolicy, RunManifest, WorkloadSpec


class CalculationApplication:
    """Run registered deterministic calculation models through one interface."""

    def __init__(self):
        self._definitions = {model.key: (model, method, parameters) for model, method, parameters in CALCULATION_DEFINITIONS}

    def list_models(self) -> list[CalculationModel]:
        return [definition[0] for definition in self._definitions.values()]

    def list_categories(self) -> tuple[str, ...]:
        return list_categories()

    def list_category(self, category: str) -> tuple[str, ...]:
        return list_category(category)

    def list_catalog_items(self, category: str | None = None):
        return list_items(category)

    def grouped_categories(self) -> dict[str, tuple[str, ...]]:
        return grouped_categories()

    def search(self, query: str, category: str | None = None) -> tuple[str, ...]:
        return search(query, category=category)

    def get_catalog_entry(self, model_key: str):
        self.get_model(model_key)
        return get_entry(model_key)

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

    def _validated_inputs(self, model_key: str, inputs: Mapping[str, object]) -> tuple[MethodVersion, tuple[CalculationParameter, ...], dict[str, float]]:
        definition = self._definitions.get(model_key)
        if definition is None:
            raise ValueError(f"Unknown calculation model: {model_key}")
        if not isinstance(inputs, Mapping):
            raise ValueError("inputs must be an object.")
        _, method, parameters = definition
        expected = {parameter.name: parameter for parameter in parameters}
        supplied = set(inputs)
        unknown = supplied - set(expected)
        if unknown:
            raise ValueError("Unknown inputs: " + ", ".join(sorted(unknown)))
        callable_parameters = inspect.signature(CALCULATION_REGISTRY[model_key].calculate).parameters
        missing = [
            name
            for name, parameter in expected.items()
            if parameter.required and name not in supplied and callable_parameters[name].default is inspect.Parameter.empty
        ]
        if missing:
            raise ValueError("Missing required inputs: " + ", ".join(missing))
        validated: dict[str, float] = {}
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

    def run_trace(self, model_key: str, inputs: Mapping[str, object]) -> CalculationTrace:
        """Validate and execute a model with an expanded, auditable solution trace."""
        _, _, validated = self._validated_inputs(model_key, inputs)
        return expand_trace(calculations.calculate_detailed(model_key, **validated))

    def run(self, model_key: str, inputs: Mapping[str, object]) -> CalculationRecord:
        trace = self.run_trace(model_key, inputs)
        method = self.get_method(model_key)
        parameters = self.get_parameters(model_key)
        return CalculationRecord(calculation_type=trace.key, inputs=trace.inputs, units={parameter.name: parameter.default_unit or "" for parameter in parameters}, assumptions=trace.assumptions, method=trace.equation, result=trace.result, result_unit=trace.result_unit, source="deterministic calculation library", method_version=method.version)

    def workload_spec(self, model_key: str, inputs: Mapping[str, object]) -> WorkloadSpec:
        """Build a reproducible workload definition for one deterministic calculation."""
        method, _, validated = self._validated_inputs(model_key, inputs)
        return WorkloadSpec(
            name=model_key,
            kind="calculation",
            inputs=validated,
            tags=("deterministic", "calculation"),
            software_version=method.version,
            policy=ExecutionPolicy(
                deterministic=True,
                checkpoint_required=True,
                allow_remote=False,
                allow_network=False,
                approval_required=False,
            ),
        )

    @staticmethod
    def _result_fingerprint(record: CalculationRecord) -> str:
        payload = {
            "calculation_type": record.calculation_type,
            "inputs": dict(record.inputs),
            "units": dict(record.units),
            "assumptions": record.assumptions,
            "method": record.method,
            "result": record.result,
            "result_unit": record.result_unit,
            "source": record.source,
            "method_version": record.method_version,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def run_with_manifest(self, model_key: str, inputs: Mapping[str, object]) -> tuple[CalculationRecord, RunManifest]:
        """Run a deterministic calculation and return its reproducibility manifest."""
        started_at = datetime.now(timezone.utc).isoformat()
        spec = self.workload_spec(model_key, inputs)
        record = self.run(model_key, inputs)
        finished_at = datetime.now(timezone.utc).isoformat()
        manifest = RunManifest(
            workload_fingerprint=spec.fingerprint(),
            backend="deterministic-calculation-library",
            status="succeeded",
            started_at=started_at,
            finished_at=finished_at,
            result_fingerprint=self._result_fingerprint(record),
        )
        return record, manifest

    def run_and_save(self, model_key: str, inputs: Mapping[str, object]) -> tuple[int, CalculationRecord]:
        record = self.run(model_key, inputs)
        calculation_id = db.save_calculation_record(record)
        if calculation_id is None:
            raise RuntimeError("Database did not return a calculation record ID.")
        return int(calculation_id), record


__all__ = ["CalculationApplication"]
