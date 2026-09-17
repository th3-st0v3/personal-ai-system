from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from automation.computer_use.contracts import Observation

from .task_runner import CompletionChecker, CompletionDecision


ObservationPredicate = Callable[[Observation], bool]


@dataclass(frozen=True)
class TaskGoal:
    """Explicit, machine-checkable requirements for declaring a task complete."""

    goal_id: str
    required_observation_kinds: tuple[str, ...] = ()
    required_sources: tuple[str, ...] = ()
    required_predicates: Mapping[str, ObservationPredicate] = ()
    minimum_verified_observations: int = 0

    def __post_init__(self) -> None:
        if not self.goal_id.strip():
            raise ValueError("goal_id is required")
        if self.minimum_verified_observations < 0:
            raise ValueError("minimum_verified_observations must be non-negative")


class EvidenceGoalChecker(CompletionChecker):
    """Complete only when explicitly configured evidence requirements are satisfied."""

    def __init__(self, goal: TaskGoal) -> None:
        self.goal = goal

    def check(self, observations: Sequence[Observation]) -> CompletionDecision:
        missing: list[str] = []

        observed_kinds = {observation.kind for observation in observations}
        for required_kind in self.goal.required_observation_kinds:
            if required_kind not in observed_kinds:
                missing.append(f"observation kind {required_kind!r} is missing")

        observed_sources = {observation.source for observation in observations}
        for required_source in self.goal.required_sources:
            if required_source not in observed_sources:
                missing.append(f"observation source {required_source!r} is missing")

        for name, predicate in self.goal.required_predicates.items():
            if not any(_safe_predicate(predicate, observation) for observation in observations):
                missing.append(f"required evidence predicate {name!r} is unsatisfied")

        if self.goal.minimum_verified_observations:
            verified_count = sum(
                1
                for observation in observations
                if _observation_status_is_verified(observation)
            )
            if verified_count < self.goal.minimum_verified_observations:
                missing.append(
                    "minimum verified observations not reached "
                    f"({verified_count}/{self.goal.minimum_verified_observations})"
                )

        if missing:
            return CompletionDecision("incomplete", "; ".join(missing))
        return CompletionDecision("complete", f"goal {self.goal.goal_id!r} requirements satisfied")


def _safe_predicate(predicate: ObservationPredicate, observation: Observation) -> bool:
    try:
        return bool(predicate(observation))
    except Exception:
        return False


def _observation_status_is_verified(observation: Observation) -> bool:
    status = observation.data.get("verification_status")
    return status == "verified"


__all__ = ["EvidenceGoalChecker", "ObservationPredicate", "TaskGoal"]
