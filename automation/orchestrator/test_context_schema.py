from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

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
    RelevantFile,
    RepositoryContext,
    ResearchContext,
    WorkingTreeContext,
    TestContext as PASITestContext,
    TestSummary as PASITestSummary,
)


def make_package() -> ContextPackage:
    return ContextPackage.create(
        context_id="ctx_test_001",
        objective=ObjectiveContext(
            primary="Make the login button work.",
            constraints=["Do not change the authentication provider."],
            success_criteria=[
                "Relevant tests pass.",
                "Browser verification succeeds.",
            ],
        ),
        project=ProjectContext(
            project_id="demo-project",
            name="Demo Project",
            repository=RepositoryContext(
                provider="github",
                repository="example/demo-project",
                branch="main",
            ),
        ),
        memory=MemoryContext(
            query="login authentication",
            notes=[],
        ),
        git_wsl=GitWslContext(
            branch="main",
            head="abc123",
            upstream="origin/main",
            sync_state="SYNCED",
            working_tree=WorkingTreeContext(
                clean=True,
                changed_files=[],
            ),
            ahead=0,
            behind=0,
        ),
        tests=PASITestContext(
            status="passed",
            frameworks=["pytest"],
            summary=PASITestSummary(
                passed=10,
                failed=0,
                skipped=0,
                errors=0,
            ),
        ),
        browser=BrowserContext(
            available=True,
            url="http://localhost:3000/login",
        ),
        files=FilesContext(),
        execution_policy=ExecutionPolicy(
            allowed_actions=["read", "test"],
            approval_required=["git_push"],
        ),
        evidence_quality=EvidenceQuality(
            overall="good",
        ),
        agent_request=AgentRequest(
            task="Determine whether the login objective is complete.",
            expected_output=["assessment", "verification plan"],
        ),
    )


def test_context_package_can_be_created() -> None:
    package = make_package()

    assert package.schema_version == "1.0"
    assert package.context_id == "ctx_test_001"
    assert package.objective.primary == "Make the login button work."
    assert package.git_wsl.sync_state == "SYNCED"
    assert package.tests.summary.passed == 10


def test_context_package_accepts_research_context() -> None:
    package = make_package()

    package.research = ResearchContext(
        objective="Make the login button work.",
        observations=["The login route exists."],
        findings=["Authentication uses the existing session layer."],
        sources_considered=["repo://src/auth.py"],
        unanswered_questions=["Browser behavior still needs verification."],
        evidence_quality="good",
    )

    assert package.research is not None
    assert package.research.objective == "Make the login button work."
    assert package.research.evidence_quality == "good"
    assert package.research.findings == [
        "Authentication uses the existing session layer."
    ]


def test_created_context_has_timezone_aware_timestamp() -> None:
    package = make_package()

    assert package.created_at.tzinfo is not None


def test_context_package_serializes_to_json() -> None:
    package = make_package()

    payload = package.to_context_dict()
    serialized = package.to_context_json()

    assert payload["context_id"] == "ctx_test_001"
    assert '"schema_version": "1.0"' in serialized
    assert "Make the login button work." in serialized


def test_created_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        ContextPackage.model_validate(
            {
                "context_id": "ctx_test_002",
                "created_at": datetime(2026, 1, 1),
                "objective": {
                    "primary": "test",
                },
                "project": {
                    "project_id": "demo",
                    "name": "Demo",
                    "repository": {
                        "provider": "github",
                        "repository": "example/demo",
                        "branch": "main",
                    },
                },
                "memory": {
                    "query": "test",
                },
                "git_wsl": {
                    "branch": "main",
                    "head": "abc",
                    "sync_state": "SYNCED",
                    "working_tree": {
                        "clean": True,
                    },
                    "ahead": 0,
                    "behind": 0,
                },
                "tests": {
                    "status": "passed",
                    "summary": {
                        "passed": 1,
                        "failed": 0,
                        "skipped": 0,
                        "errors": 0,
                    },
                },
                "browser": {
                    "available": False,
                },
                "files": {},
                "execution_policy": {},
                "evidence_quality": {},
                "agent_request": {
                    "task": "test",
                },
            }
        )

def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ObjectiveContext.model_validate(
            {
                "primary": "test",
                "unexpected": "should fail",
            }
        )

def test_relevance_scores_are_bounded() -> None:
    with pytest.raises(ValidationError):
        RelevantFile.model_validate(
            {
                "path": "src/login.py",
                "reason": "login implementation",
                "relevance": 1.5,
            }
        )

def test_sync_state_is_constrained() -> None:
    with pytest.raises(ValidationError):
        GitWslContext.model_validate(
            {
                "branch": "main",
                "head": "abc",
                "sync_state": "MAKE_SOMETHING_UP",
                "working_tree": {
                    "clean": True,
                },
                "ahead": 0,
                "behind": 0,
            }
        )

def test_checked_in_json_schema_matches_context_package() -> None:
    import json
    from pathlib import Path

    schema_path = Path(__file__).with_name(
        "context_package.schema.json"
    )

    checked_in = json.loads(schema_path.read_text())
    generated = ContextPackage.model_json_schema()

    assert checked_in == generated
