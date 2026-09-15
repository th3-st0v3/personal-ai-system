from __future__ import annotations

from automation.orchestrator.context_schema import (
    AgentRequest,
    BrowserContext,
    ContextPackage,
    EvidenceQuality,
    ExecutionPolicy,
    FilesContext,
    GitWslContext,
    MemoryContext,
    ObjectiveContext,
    ProjectContext,
    RepositoryContext,
    TestContext as ContextTestContext,
    TestSummary as ContextTestSummary,
    WorkingTreeContext,
)
from automation.orchestrator.fake_planner_adapter import FakePlannerAdapter
from automation.orchestrator.planner_adapter import PlannerAdapter
from automation.orchestrator.planner_schema import PlannerResult, ProposedStep


def make_context_package() -> ContextPackage:
    return ContextPackage.create(
        context_id="context-test-1",
        objective=ObjectiveContext(
            primary="Implement and verify a login feature.",
        ),
        project=ProjectContext(
            project_id="project-test-1",
            name="test-project",
            repository=RepositoryContext(
                provider="github",
                repository="test-project",
                branch="main",
            ),
        ),
        memory=MemoryContext(
            query="Implement and verify a login feature.",
        ),
        git_wsl=GitWslContext(
            branch="main",
            head="abc123",
            sync_state="SYNCED",
            working_tree=WorkingTreeContext(
                clean=True,
            ),
            ahead=0,
            behind=0,
        ),
        tests=ContextTestContext(
            status="not_run",
            summary=ContextTestSummary(
                passed=0,
                failed=0,
                skipped=0,
                errors=0,
            ),
        ),
        browser=BrowserContext(
            available=False,
        ),
        files=FilesContext(),
        execution_policy=ExecutionPolicy(),
        evidence_quality=EvidenceQuality(),
        agent_request=AgentRequest(
            task="Implement and verify a login feature.",
        ),
    )


def make_request() -> AgentRequest:
    return AgentRequest(
        task="Implement and verify a login feature.",
        expected_output=[
            "proposed plan",
            "required verification",
        ],
        restrictions=[
            "Do not execute actions.",
        ],
    )


def test_fake_planner_adapter_implements_protocol() -> None:
    adapter: PlannerAdapter = FakePlannerAdapter()
    result = adapter.plan(make_request(), make_context_package())

    assert isinstance(result, PlannerResult)


def test_fake_planner_adapter_is_deterministic() -> None:
    request = make_request()
    context = make_context_package()

    adapter = FakePlannerAdapter(
        proposed_steps=[
            ProposedStep(
                step_id="step-1",
                description="Inspect the login implementation.",
            )
        ],
        verification_requirements=[
            "Run the relevant tests.",
        ],
    )

    first = adapter.plan(request, context)
    second = adapter.plan(request, context)

    assert first == second
    assert len(adapter.requests) == 2
    assert adapter.requests[0] == (request, context)
    assert adapter.requests[1] == (request, context)


def test_fake_planner_adapter_returns_configured_result() -> None:
    adapter = FakePlannerAdapter(
        proposed_steps=[
            ProposedStep(
                step_id="step-1",
                description="Implement the login flow.",
            ),
            ProposedStep(
                step_id="step-2",
                description="Verify the login flow in tests.",
            ),
        ],
        required_capabilities=["filesystem", "test_runner"],
        verification_requirements=[
            "All relevant tests pass.",
            "Browser behavior is verified.",
        ],
        blockers=["Browser verification is not currently available."],
    )

    result = adapter.plan(make_request(), make_context_package())

    assert result.proposed_steps == [
        ProposedStep(
            step_id="step-1",
            description="Implement the login flow.",
        ),
        ProposedStep(
            step_id="step-2",
            description="Verify the login flow in tests.",
        ),
    ]
    assert result.required_capabilities == [
        "filesystem",
        "test_runner",
    ]
    assert result.verification_requirements == [
        "All relevant tests pass.",
        "Browser behavior is verified.",
    ]
    assert result.blockers == [
        "Browser verification is not currently available."
    ]


def test_fake_planner_adapter_defaults_to_empty_result() -> None:
    result = FakePlannerAdapter().plan(
        make_request(),
        make_context_package(),
    )

    assert result.proposed_steps == []
    assert result.required_capabilities == []
    assert result.verification_requirements == []
    assert result.blockers == []


def test_fake_planner_adapter_keeps_request_and_context_separate_from_result() -> None:
    request = make_request()
    context = make_context_package()

    result = FakePlannerAdapter(
        blockers=["Example blocker."]
    ).plan(request, context)

    assert result.proposed_steps == []
    assert result.blockers == ["Example blocker."]
