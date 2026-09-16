from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from .authorized_executor import AuthorizedExecutor
from .context_schema import ContextPackage
from .execution_schema import ExecutionRequest, ExecutionResult
from .execution_authorization import authorize_plan
from .models import CurrentTask, ProjectState
from .orchestration_state import transition
from .planner_schema import PlannerResult, ProposedStep
from .state import StateManager
from .test_runner import TestResult, TestRunner


@dataclass(frozen=True)
class BrowserVerificationResult:
    success: bool
    details: str = ""


@dataclass(frozen=True)
class Diagnosis:
    source: str
    reason: str
    details: str = ""


class BrowserVerifier(Protocol):
    def verify(self) -> BrowserVerificationResult:
        """Verify the browser-facing requirements for the current task."""
        ...


class Replanner(Protocol):
    def replan(
        self,
        plan: PlannerResult,
        context: ContextPackage,
        diagnosis: Diagnosis,
    ) -> PlannerResult:
        """Produce a replacement plan using the new failure evidence."""
        ...


@dataclass(frozen=True)
class ExecutionLoopResult:
    status: str
    plan: PlannerResult
    execution_results: tuple[ExecutionResult, ...]
    test_results: tuple[TestResult, ...]
    browser_result: BrowserVerificationResult | None
    diagnosis: Diagnosis | None
    replans: int


def _step_action(step: ProposedStep) -> str | None:
    from .execution_authorization import CAPABILITY_TO_ACTION

    actions = {
        CAPABILITY_TO_ACTION[capability]
        for capability in step.required_capabilities
        if capability in CAPABILITY_TO_ACTION
    }

    if len(actions) != 1:
        return None

    return next(iter(actions))


def _save_state(
    state: StateManager,
    task: CurrentTask,
    project_state: ProjectState,
) -> None:
    state.save_current_task(task)
    state.save_project_state(project_state)


def _save_retry_state(
    state: StateManager,
    *,
    task: CurrentTask,
    replans: int,
    max_replans: int,
    diagnosis: Diagnosis | None,
) -> None:
    state.save_retry_state(
        {
            "task_id": task.task_id,
            "attempt": task.attempt,
            "replans": replans,
            "max_replans": max_replans,
            "source": diagnosis.source if diagnosis else None,
            "reason": diagnosis.reason if diagnosis else None,
            "details": diagnosis.details if diagnosis else None,
        }
    )


def _diagnose_execution_failure(result: ExecutionResult) -> Diagnosis:
    return Diagnosis(
        source="execution",
        reason=result.error or "Execution did not complete successfully.",
        details=f"step_id={result.step_id}; action={result.action}; status={result.status}",
    )


def _diagnose_test_failure(results: list[TestResult]) -> Diagnosis:
    failed = [
        result
        for result in results
        if not result.success
    ]
    details = "; ".join(
        f"{' '.join(result.command)} -> exit {result.return_code}"
        for result in failed
    )
    return Diagnosis(
        source="testing",
        reason="One or more project test commands failed.",
        details=details,
    )


def _diagnose_browser_failure(
    result: BrowserVerificationResult,
) -> Diagnosis:
    return Diagnosis(
        source="browser_verification",
        reason="Browser verification failed.",
        details=result.details,
    )


def run_supervised_execution(
    connection: sqlite3.Connection,
    *,
    actor_id: str,
    task: CurrentTask,
    project_state: ProjectState,
    plan: PlannerResult,
    context: ContextPackage,
    state: StateManager,
    executor: AuthorizedExecutor,
    test_runner: TestRunner,
    human_approval_granted: bool = False,
    browser_verifier: BrowserVerifier | None = None,
    replanner: Replanner | None = None,
    max_replans: int = 2,
) -> ExecutionLoopResult:
    """Run the supervised execution/verification loop without owning provider adapters."""
    execution_results: list[ExecutionResult] = []
    test_results: list[TestResult] = []
    browser_result: BrowserVerificationResult | None = None
    diagnosis: Diagnosis | None = None
    replans = 0
    _save_retry_state(
        state,
        task=task,
        replans=replans,
        max_replans=max_replans,
        diagnosis=None,
    )

    while True:
        if plan.blockers:
            diagnosis = Diagnosis(
                source="planning",
                reason="Planner returned blockers.",
                details="; ".join(plan.blockers),
            )
            _save_retry_state(
                state,
                task=task,
                replans=replans,
                max_replans=max_replans,
                diagnosis=diagnosis,
            )
            transition(task, project_state, "handoff")
            _save_state(state, task, project_state)
            return ExecutionLoopResult(
                status="handoff",
                plan=plan,
                execution_results=tuple(execution_results),
                test_results=tuple(test_results),
                browser_result=browser_result,
                diagnosis=diagnosis,
                replans=replans,
            )

        decision = authorize_plan(
            connection,
            actor_id=actor_id,
            plan=plan,
            human_approval_granted=human_approval_granted,
        )

        if not decision.allowed:
            if decision.human_approval_required and not human_approval_granted:
                diagnosis = Diagnosis(
                    source="authorization",
                    reason=decision.reason,
                    details="; ".join(decision.required_actions),
                )
                _save_retry_state(
                    state,
                    task=task,
                    replans=replans,
                    max_replans=max_replans,
                    diagnosis=diagnosis,
                )
                transition(task, project_state, "awaiting_approval")
                _save_state(state, task, project_state)
                return ExecutionLoopResult(
                    status="awaiting_approval",
                    plan=plan,
                    execution_results=tuple(execution_results),
                    test_results=tuple(test_results),
                    browser_result=browser_result,
                    diagnosis=diagnosis,
                    replans=replans,
                )

            diagnosis = Diagnosis(
                source="authorization",
                reason=decision.reason,
                details="; ".join(decision.denied_actions or decision.unknown_capabilities),
            )
            _save_retry_state(
                state,
                task=task,
                replans=replans,
                max_replans=max_replans,
                diagnosis=diagnosis,
            )
            transition(task, project_state, "handoff")
            _save_state(state, task, project_state)
            return ExecutionLoopResult(
                status="handoff",
                plan=plan,
                execution_results=tuple(execution_results),
                test_results=tuple(test_results),
                browser_result=browser_result,
                diagnosis=diagnosis,
                replans=replans,
            )

        if not plan.proposed_steps:
            transition(task, project_state, "completed")
            _save_state(state, task, project_state)
            _save_retry_state(
                state,
                task=task,
                replans=replans,
                max_replans=max_replans,
                diagnosis=None,
            )
            return ExecutionLoopResult(
                status="completed",
                plan=plan,
                execution_results=tuple(execution_results),
                test_results=tuple(test_results),
                browser_result=browser_result,
                diagnosis=None,
                replans=replans,
            )

        transition(task, project_state, "executing")
        _save_state(state, task, project_state)

        step_failure: Diagnosis | None = None

        for step in plan.proposed_steps:
            action = _step_action(step)
            if action is None:
                step_failure = Diagnosis(
                    source="planning",
                    reason="A proposed step does not resolve to exactly one known policy action.",
                    details=f"step_id={step.step_id}; capabilities={step.required_capabilities}",
                )
                break

            result = executor.execute(
                ExecutionRequest(
                    request_id=f"req_{uuid4().hex}",
                    task_id=task.task_id,
                    step_id=step.step_id,
                    actor_id=actor_id,
                    action=action,
                    human_approval_granted=human_approval_granted,
                )
            )
            execution_results.append(result)
            state.save_execution_result(result)

            if result.status != "executed":
                step_failure = _diagnose_execution_failure(result)
                break

        if step_failure is not None:
            diagnosis = step_failure
            _save_retry_state(
                state,
                task=task,
                replans=replans,
                max_replans=max_replans,
                diagnosis=diagnosis,
            )
            transition(task, project_state, "diagnosis")
            _save_state(state, task, project_state)
        else:
            transition(task, project_state, "testing")
            _save_state(state, task, project_state)

            test_results = list(test_runner.run_project_tests())
            for result in test_results:
                state.save_test_results(
                    {
                        "success": result.success,
                        "command": result.command,
                        "return_code": result.return_code,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "duration_seconds": result.duration_seconds,
                    }
                )

            if any(not result.success for result in test_results):
                diagnosis = _diagnose_test_failure(test_results)
                _save_retry_state(
                    state,
                    task=task,
                    replans=replans,
                    max_replans=max_replans,
                    diagnosis=diagnosis,
                )
                transition(task, project_state, "diagnosis")
                _save_state(state, task, project_state)
            else:
                needs_browser = any(
                    "browser" in requirement.lower()
                    for requirement in plan.verification_requirements
                    + [
                        requirement
                        for step in plan.proposed_steps
                        for requirement in step.verification_requirements
                    ]
                )

                if needs_browser:
                    if browser_verifier is None:
                        diagnosis = Diagnosis(
                            source="browser_verification",
                            reason="Browser verification was required but no verifier was provided.",
                        )
                        _save_retry_state(
                            state,
                            task=task,
                            replans=replans,
                            max_replans=max_replans,
                            diagnosis=diagnosis,
                        )
                        transition(task, project_state, "diagnosis")
                        _save_state(state, task, project_state)
                    else:
                        transition(task, project_state, "browser_verification")
                        _save_state(state, task, project_state)
                        browser_result = browser_verifier.verify()
                        state.save_browser_results(
                            {
                                "success": browser_result.success,
                                "details": browser_result.details,
                            }
                        )

                        if not browser_result.success:
                            diagnosis = _diagnose_browser_failure(browser_result)
                            _save_retry_state(
                                state,
                                task=task,
                                replans=replans,
                                max_replans=max_replans,
                                diagnosis=diagnosis,
                            )
                            transition(task, project_state, "diagnosis")
                            _save_state(state, task, project_state)
                        else:
                            transition(task, project_state, "completed")
                            _save_state(state, task, project_state)
                            _save_retry_state(
                                state,
                                task=task,
                                replans=replans,
                                max_replans=max_replans,
                                diagnosis=None,
                            )
                            return ExecutionLoopResult(
                                status="completed",
                                plan=plan,
                                execution_results=tuple(execution_results),
                                test_results=tuple(test_results),
                                browser_result=browser_result,
                                diagnosis=None,
                                replans=replans,
                            )
                else:
                    transition(task, project_state, "completed")
                    _save_state(state, task, project_state)
                    _save_retry_state(
                        state,
                        task=task,
                        replans=replans,
                        max_replans=max_replans,
                        diagnosis=None,
                    )
                    return ExecutionLoopResult(
                        status="completed",
                        plan=plan,
                        execution_results=tuple(execution_results),
                        test_results=tuple(test_results),
                        browser_result=browser_result,
                        diagnosis=None,
                        replans=replans,
                    )

        if diagnosis is None:
            raise RuntimeError("Execution loop reached an unexpected state without a diagnosis.")

        if replanner is None or replans >= max_replans:
            _save_retry_state(
                state,
                task=task,
                replans=replans,
                max_replans=max_replans,
                diagnosis=diagnosis,
            )
            transition(task, project_state, "handoff")
            _save_state(state, task, project_state)
            return ExecutionLoopResult(
                status="handoff",
                plan=plan,
                execution_results=tuple(execution_results),
                test_results=tuple(test_results),
                browser_result=browser_result,
                diagnosis=diagnosis,
                replans=replans,
            )

        transition(task, project_state, "replanning")
        task.attempt += 1
        task.implementation_attempts += 1
        replans += 1
        _save_retry_state(
            state,
            task=task,
            replans=replans,
            max_replans=max_replans,
            diagnosis=diagnosis,
        )
        _save_state(state, task, project_state)

        plan = replanner.replan(plan, context, diagnosis)

        transition(task, project_state, "planning")
        _save_state(state, task, project_state)
