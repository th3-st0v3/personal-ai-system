"""Small deterministic verification primitives for engineering workloads."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    value: float | None = None
    expected: float | None = None
    tolerance: float | None = None
    message: str = ""


def relative_error(actual: float, expected: float) -> float:
    """Return a bounded relative error, using absolute error at zero."""
    if not isfinite(actual) or not isfinite(expected):
        raise ValueError("actual and expected must be finite")
    scale = max(abs(expected), 1e-30)
    return abs(actual - expected) / scale


def scalar_balance(name: str, actual: float, expected: float, tolerance: float = 1e-6) -> CheckResult:
    """Check a scalar conservation/balance quantity against an expected value."""
    if tolerance < 0:
        raise ValueError("tolerance must not be negative")
    error = relative_error(actual, expected)
    return CheckResult(
        name=name,
        passed=error <= tolerance,
        value=actual,
        expected=expected,
        tolerance=tolerance,
        message=f"relative_error={error:.6g}",
    )


def mesh_convergence(values: list[float] | tuple[float, ...], tolerance: float = 0.01) -> CheckResult:
    """Basic three-level convergence check for a scalar mesh output.

    This is a screening primitive, not a substitute for a domain-specific GCI
    implementation. It requires three finite values and checks that the final
    refinement changes the result by no more than the configured tolerance.
    """
    if len(values) != 3:
        raise ValueError("mesh convergence requires exactly three values")
    if tolerance < 0:
        raise ValueError("tolerance must not be negative")
    coarse, medium, fine = values
    if not all(isfinite(value) for value in values):
        raise ValueError("mesh values must be finite")
    error = relative_error(fine, medium)
    return CheckResult(
        name="mesh_convergence",
        passed=error <= tolerance,
        value=fine,
        expected=medium,
        tolerance=tolerance,
        message=f"final_refinement_relative_change={error:.6g}; levels={coarse},{medium},{fine}",
    )


def require_all(checks: list[CheckResult] | tuple[CheckResult, ...]) -> None:
    """Raise a compact error if any verification check fails."""
    failures = [check.name for check in checks if not check.passed]
    if failures:
        raise ValueError("verification failed: " + ", ".join(failures))
