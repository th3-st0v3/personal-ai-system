"""Bounded fuzzing of registered deterministic calculations and simulations."""
from __future__ import annotations

import hashlib
import json
import math
import random
import time
from typing import Any

import simulation_library
from calculation_application import CalculationApplication


_MAX_ITERATIONS = 5000
_MAX_SAMPLE_CASES = 60
_POSITIVE_NAMES = {
    "area", "diameter", "depth", "density", "thickness", "velocity", "viscosity", "conductivity",
}


def _mutate(value: float, rng: random.Random, name: str) -> float:
    positive = name.casefold() in _POSITIVE_NAMES
    if rng.random() < 0.08:
        candidate = 0.0
    elif rng.random() < 0.12:
        candidate = -abs(value or 1.0) * rng.uniform(0.1, 2.0)
    elif value == 0:
        candidate = rng.uniform(-10.0, 10.0)
    else:
        candidate = value * math.exp(rng.uniform(-1.75, 1.75))
    if positive and candidate <= 0:
        candidate = abs(candidate) or 1e-9
    return candidate


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_fuzz(
    target_kind: str,
    target_key: str,
    base_inputs: dict[str, float] | None = None,
    *,
    iterations: int = 100,
    seed: int = 1,
) -> dict[str, object]:
    iterations = int(iterations)
    if not 1 <= iterations <= _MAX_ITERATIONS:
        raise ValueError(f"iterations must be between 1 and {_MAX_ITERATIONS}.")
    if target_kind not in {"simulation", "calculation"}:
        raise ValueError("target_kind must be 'simulation' or 'calculation'.")
    rng = random.Random(int(seed))
    app = CalculationApplication()
    provided = {str(k): float(v) for k, v in (base_inputs or {}).items()}

    if target_kind == "simulation":
        target = simulation_library.get_simulation(target_key)
        names = list(target.parameters)
        base = {name: provided.get(name, 1.0) for name in names}
        runner = lambda values: simulation_library.run_simulation(target_key, values)
    else:
        target = app.get_model(target_key)
        parameters = app.get_parameters(target_key)
        names = [parameter.name for parameter in parameters]
        base = {}
        for parameter in parameters:
            if parameter.name in provided:
                base[parameter.name] = provided[parameter.name]
            elif parameter.minimum is not None and parameter.maximum is not None:
                base[parameter.name] = (parameter.minimum + parameter.maximum) / 2.0
            elif parameter.minimum is not None:
                base[parameter.name] = parameter.minimum + 1.0
            elif parameter.maximum is not None:
                base[parameter.name] = parameter.maximum - 1.0
            else:
                base[parameter.name] = 1.0
        runner = lambda values: app.run_trace(target_key, values).to_dict()

    started = time.perf_counter()
    successes = 0
    failures: list[dict[str, object]] = []
    samples: list[dict[str, object]] = []
    for index in range(iterations):
        values = {name: _mutate(float(base[name]), rng, name) for name in names}
        try:
            result = runner(values)
            successes += 1
            if len(samples) < _MAX_SAMPLE_CASES:
                samples.append({"index": index, "inputs": values, "ok": True, "result": result})
        except Exception as exc:
            failures.append({
                "index": index,
                "inputs": values,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            if len(samples) < _MAX_SAMPLE_CASES:
                samples.append({"index": index, "inputs": values, "ok": False, "error": str(exc)})
    elapsed = time.perf_counter() - started
    payload = {
        "schema_version": "1",
        "target": {"kind": target_kind, "key": target_key},
        "seed": int(seed),
        "iterations": iterations,
        "successes": successes,
        "failures": len(failures),
        "failure_examples": failures[:20],
        "sample_cases": samples,
        "duration_seconds": round(elapsed, 6),
    }
    payload["fingerprint"] = _fingerprint(payload)
    return payload


__all__ = ["run_fuzz"]
