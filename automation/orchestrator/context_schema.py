from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SCHEMA_VERSION = "1.0"

SyncState = Literal[
    "SYNCED",
    "LOCAL_AHEAD",
    "REMOTE_AHEAD",
    "DIVERGED",
    "DIRTY_LOCAL",
    "UNKNOWN",
]

TestStatus = Literal[
    "passed",
    "failed",
    "error",
    "skipped",
    "not_run",
    "unknown",
]

GenericStatus = Literal[
    "pass",
    "fail",
    "unknown",
]

Priority = Literal[
    "low",
    "normal",
    "high",
    "critical",
]


class PASIModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )


class ObjectiveContext(PASIModel):
    primary: str = Field(min_length=1)
    scope: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    priority: Priority = "normal"


class RepositoryContext(PASIModel):
    provider: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    branch: str = Field(min_length=1)


class ProjectContext(PASIModel):
    project_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    repository: RepositoryContext


class MemoryNote(PASIModel):
    path: str = Field(min_length=1)
    relevance: float = Field(ge=0.0, le=1.0)
    content: str = Field(min_length=1)


class MemoryContext(PASIModel):
    source: Literal["obsidian"] = "obsidian"
    query: str = Field(min_length=1)
    notes: list[MemoryNote] = Field(default_factory=list)


class WorkingTreeContext(PASIModel):
    clean: bool
    changed_files: list[str] = Field(default_factory=list)


class DiffSummary(PASIModel):
    files_changed: int = Field(ge=0)
    insertions: int = Field(ge=0)
    deletions: int = Field(ge=0)


class GitWslContext(PASIModel):
    branch: str = Field(min_length=1)
    head: str = Field(min_length=1)
    upstream: str | None = None
    sync_state: SyncState
    working_tree: WorkingTreeContext
    ahead: int = Field(ge=0)
    behind: int = Field(ge=0)
    recent_commits: list[str] = Field(default_factory=list)
    diff_summary: DiffSummary | None = None


class TestFailure(PASIModel):
    name: str = Field(min_length=1)
    file: str | None = None
    message: str | None = None
    traceback: str | None = None
    evidence: str | None = None


class TestSummary(PASIModel):
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0)
    errors: int = Field(ge=0)


class BuildContext(PASIModel):
    status: TestStatus
    command: str | None = None


class TestContext(PASIModel):
    status: TestStatus
    frameworks: list[str] = Field(default_factory=list)
    summary: TestSummary
    failures: list[TestFailure] = Field(default_factory=list)
    build: BuildContext | None = None


class BrowserControl(PASIModel):
    id: str = Field(min_length=1)
    control: str = Field(min_length=1)
    role: str | None = None
    name: str | None = None
    visible: bool = True
    enabled: bool | None = None


class BrowserPageContext(PASIModel):
    title: str | None = None
    type: str | None = None


class BrowserRuntimeState(PASIModel):
    loading: bool | None = None


class BrowserContext(PASIModel):
    available: bool
    url: str | None = None
    page: BrowserPageContext | None = None
    observation_id: str | None = None
    controls: list[BrowserControl] = Field(default_factory=list)
    visible_errors: list[str] = Field(default_factory=list)
    runtime_state: BrowserRuntimeState | None = None


class RelevantFile(PASIModel):
    path: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    relevance: float = Field(ge=0.0, le=1.0)


class ExcludedFile(PASIModel):
    path: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class FilesContext(PASIModel):
    relevant: list[RelevantFile] = Field(default_factory=list)
    excluded: list[ExcludedFile] = Field(default_factory=list)


class AttemptResult(PASIModel):
    claim: str | None = None
    status: Literal["fact", "hypothesis", "verified", "failed", "unknown"] = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class PreviousAttempt(PASIModel):
    attempt_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    action: str = Field(min_length=1)
    result: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    status: Literal["success", "failed", "partial", "unknown"] = "unknown"
    conclusions: list[AttemptResult] = Field(default_factory=list)


class Capability(PASIModel):
    name: str = Field(min_length=1)
    available: bool = True
    authorized: bool = False


class ExecutionPolicy(PASIModel):
    allowed_actions: list[str] = Field(default_factory=list)
    approval_required: list[str] = Field(default_factory=list)


class EvidenceQuality(PASIModel):
    overall: Literal["poor", "fair", "good", "strong", "unknown"] = "unknown"
    missing: list[str] = Field(default_factory=list)
    stale: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)

    @field_validator("overall", mode="before")
    @classmethod
    def normalize_unknown(cls, value: str) -> str:
        return "unknown" if value == "unknown" else value


class AgentRequest(PASIModel):
    task: str = Field(min_length=1)
    expected_output: list[str] = Field(default_factory=list)
    restrictions: list[str] = Field(default_factory=list)


class ContextPackage(PASIModel):
    schema_version: str = SCHEMA_VERSION
    context_id: str = Field(min_length=1)
    created_at: datetime
    objective: ObjectiveContext
    project: ProjectContext
    memory: MemoryContext
    git_wsl: GitWslContext
    tests: TestContext
    browser: BrowserContext
    files: FilesContext
    previous_attempts: list[PreviousAttempt] = Field(default_factory=list)
    available_capabilities: list[Capability] = Field(default_factory=list)
    execution_policy: ExecutionPolicy
    evidence_quality: EvidenceQuality
    agent_request: AgentRequest

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must include timezone information")
        return value

    @classmethod
    def create(
        cls,
        *,
        context_id: str,
        objective: ObjectiveContext,
        project: ProjectContext,
        memory: MemoryContext,
        git_wsl: GitWslContext,
        tests: TestContext,
        browser: BrowserContext,
        files: FilesContext,
        previous_attempts: list[PreviousAttempt] | None = None,
        available_capabilities: list[Capability] | None = None,
        execution_policy: ExecutionPolicy | None = None,
        evidence_quality: EvidenceQuality | None = None,
        agent_request: AgentRequest | None = None,
    ) -> "ContextPackage":
        return cls(
            context_id=context_id,
            created_at=datetime.now(timezone.utc),
            objective=objective,
            project=project,
            memory=memory,
            git_wsl=git_wsl,
            tests=tests,
            browser=browser,
            files=files,
            previous_attempts=previous_attempts or [],
            available_capabilities=available_capabilities or [],
            execution_policy=execution_policy or ExecutionPolicy(),
            evidence_quality=evidence_quality or EvidenceQuality(
                overall="unknown"
            ),
            agent_request=agent_request or AgentRequest(
                task="Determine the next useful engineering action."
            ),
        )

    def to_context_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    def to_context_json(self, *, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)
