from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .context_schema import (
    AgentRequest,
    BrowserContext,
    BrowserPageContext,
    Capability,
    ContextPackage,
    DiffSummary,
    EvidenceQuality,
    ExecutionPolicy,
    FilesContext,
    GitWslContext,
    SyncState,
    MemoryContext,
    ObjectiveContext,
    ProjectContext,
    RelevantFile,
    RepositoryContext,
    ResearchContext,
    TestContext,
    TestSummary,
    TestFailure,
    TestStatus,
    WorkingTreeContext,
)
from .state import StateManager
from .git_manager import GitManager


@dataclass(frozen=True)
class ContextBuilderConfig:
    recent_commit_limit: int = 10
    max_changed_files: int = 100


class ContextBuilder:
    """Read-only assembler for PASI's provider-independent ContextPackage."""

    def __init__(
        self,
        *,
        project_root: Path,
        git: GitManager,
        state: StateManager,
        config: ContextBuilderConfig | None = None,
    ) -> None:
        self.project_root = project_root
        self.git = git
        self.state = state
        self.config = config or ContextBuilderConfig()

    def build(
        self,
        *,
        objective: ObjectiveContext,
        execution_policy: ExecutionPolicy | None = None,
        available_capabilities: list[Capability] | None = None,
        memory: MemoryContext | None = None,
        research: ResearchContext | None = None,
        browser: BrowserContext | None = None,
        previous_attempts: list[Any] | None = None,
        agent_request: AgentRequest | None = None,
    ) -> ContextPackage:
        git_context = self._build_git_context()
        tests = self._build_test_context()
        files = self._build_files_context(git_context)
        project = self._build_project_context(git_context)

        capabilities = (
            available_capabilities
            if available_capabilities is not None
            else self._default_capabilities()
        )

        policy = execution_policy or ExecutionPolicy()

        memory_context = memory or MemoryContext(
            query=objective.primary,
            notes=[],
        )

        browser_context = browser or self._load_browser_context()

        evidence_quality = self._build_evidence_quality(
            memory=memory_context,
            browser=browser_context,
            git=git_context,
            tests=tests,
        )

        request = agent_request or AgentRequest(
            task=objective.primary,
        )

        return ContextPackage.create(
            context_id=f"ctx_{uuid4().hex}",
            objective=objective,
            project=project,
            memory=memory_context,
            git_wsl=git_context,
            tests=tests,
            research=research,
            browser=browser_context,
            files=files,
            previous_attempts=previous_attempts or [],
            available_capabilities=capabilities,
            execution_policy=policy,
            evidence_quality=evidence_quality,
            agent_request=request,
        )

    def _build_project_context(
        self,
        git_context: GitWslContext,
    ) -> ProjectContext:
        remote = self.git.run(
            "remote",
            "get-url",
            "origin",
        )

        repository = (
            remote.stdout.strip()
            if remote.success and remote.stdout.strip()
            else self.project_root.name
        )

        if repository.endswith(".git"):
            repository = repository[:-4]

        return ProjectContext(
            project_id=self.project_root.name,
            name=self.project_root.name,
            repository=RepositoryContext(
                provider="git",
                repository=repository,
                branch=git_context.branch,
            ),
        )

    def _build_git_context(self) -> GitWslContext:
        branch = self.git.current_branch() or "DETACHED"
        head = self.git.head_commit() or "UNKNOWN"

        status = self.git.status()
        status_text = status.stdout.rstrip()

        changed_files = self._parse_changed_files(status_text)
        clean = not changed_files and status.success

        upstream = self._upstream(branch)
        ahead, behind, sync_state = self._sync_state(upstream)

        recent = self.git.recent_commits(
            limit=self.config.recent_commit_limit,
        )

        recent_commits = [
            line.strip()
            for line in recent.stdout.splitlines()
            if line.strip()
        ] if recent.success else []

        diff_summary = self._parse_diff_summary()

        return GitWslContext(
            branch=branch,
            head=head,
            upstream=upstream,
            sync_state=sync_state,
            working_tree=WorkingTreeContext(
                clean=clean,
                changed_files=changed_files[:self.config.max_changed_files],
            ),
            ahead=ahead,
            behind=behind,
            recent_commits=recent_commits,
            diff_summary=diff_summary,
        )

    def _upstream(self, branch: str) -> str | None:
        if branch == "DETACHED":
            return None

        result = self.git.run(
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{u}",
        )

        if not result.success:
            return None

        value = result.stdout.strip()
        return value or None

    def _sync_state(
        self,
        upstream: str | None,
    ) -> tuple[int, int, SyncState]:
        if upstream is None:
            return 0, 0, "UNKNOWN"

        result = self.git.run(
            "rev-list",
            "--left-right",
            "--count",
            f"HEAD...{upstream}",
        )

        if not result.success:
            return 0, 0, "UNKNOWN"

        parts = result.stdout.strip().split()

        if len(parts) != 2:
            return 0, 0, "UNKNOWN"

        try:
            ahead = int(parts[0])
            behind = int(parts[1])
        except ValueError:
            return 0, 0, "UNKNOWN"

        if ahead == 0 and behind == 0:
            state: SyncState = "SYNCED"
        elif ahead > 0 and behind == 0:
            state = "LOCAL_AHEAD"
        elif ahead == 0 and behind > 0:
            state = "REMOTE_AHEAD"
        else:
            state = "DIVERGED"

        return ahead, behind, state

    def _parse_diff_summary(self) -> DiffSummary | None:
        result = self.git.diff_stat()

        if not result.success:
            return None

        text = result.stdout.strip()

        if not text:
            return DiffSummary(
                files_changed=0,
                insertions=0,
                deletions=0,
            )

        match = re.search(
            r"(\d+)\s+files?\s+changed"
            r"(?:,\s+(\d+)\s+insertions?\(\+\))?"
            r"(?:,\s+(\d+)\s+deletions?\(-\))?",
            text,
        )

        if match is None:
            return None

        return DiffSummary(
            files_changed=int(match.group(1)),
            insertions=int(match.group(2) or 0),
            deletions=int(match.group(3) or 0),
        )

    @staticmethod
    def _parse_changed_files(
        status_text: str,
    ) -> list[str]:
        files: list[str] = []

        for line in status_text.splitlines():
            if len(line) < 4:
                continue

            path = line[3:].strip()

            if " -> " in path:
                path = path.split(" -> ", 1)[1].strip()

            path = path.strip('"')

            if path:
                files.append(path)

        return files

    def _build_files_context(
        self,
        git_context: GitWslContext,
    ) -> FilesContext:
        relevant = [
            RelevantFile(
                path=path,
                reason="Changed in the current Git working tree.",
                relevance=1.0,
            )
            for path in git_context.working_tree.changed_files
        ]

        return FilesContext(
            relevant=relevant,
            excluded=[],
        )

    def _build_test_context(self) -> TestContext:
        stored = self.state.read_json(
            self.state.test_results_path,
            {},
        )

        if not isinstance(stored, dict):
            return self._unknown_test_context()

        command_value = stored.get("command")
        stdout = str(stored.get("stdout", ""))
        stderr = str(stored.get("stderr", ""))
        return_code = stored.get("return_code")

        if not isinstance(return_code, int):
            return self._unknown_test_context()

        status: TestStatus = (
            "passed" if return_code == 0 else "failed"
        )

        summary = self._parse_test_summary(stdout + "\n" + stderr)

        return TestContext(
            status=status,
            frameworks=self._detect_frameworks(
                command_value,
                stdout,
                stderr,
            ),
            summary=summary,
            failures=(
                []
                if return_code == 0
                else [
                    TestFailure(
                        name="persisted test run",
                        message=stderr.strip() or stdout.strip() or None,
                        evidence=stdout.strip() or None,
                    )
                ]
            ),
        )

    @staticmethod
    def _unknown_test_context() -> TestContext:
        return TestContext(
            status="unknown",
            frameworks=[],
            summary=TestSummary(
                passed=0,
                failed=0,
                skipped=0,
                errors=0,
            ),
        )

    @staticmethod
    def _parse_test_summary(text: str) -> TestSummary:
        def count(pattern: str) -> int:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            return int(match.group(1)) if match else 0

        return TestSummary(
            passed=count(r"(\d+)\s+passed\b"),
            failed=count(r"(\d+)\s+failed\b"),
            skipped=count(r"(\d+)\s+skipped\b"),
            errors=count(r"(\d+)\s+errors?\b"),
        )

    @staticmethod
    def _detect_frameworks(
        command_value: Any,
        stdout: str,
        stderr: str,
    ) -> list[str]:
        command_text = " ".join(
            str(item)
            for item in command_value
        ) if isinstance(command_value, list) else str(command_value or "")

        combined = f"{command_text}\n{stdout}\n{stderr}"
        frameworks: list[str] = []

        if "pytest" in combined.lower():
            frameworks.append("pytest")

        if "npm test" in combined.lower():
            frameworks.append("npm")

        return frameworks

    def _load_browser_context(self) -> BrowserContext:
        stored = self.state.load_browser_results()

        if not stored:
            return BrowserContext(available=False)

        url = stored.get("url")
        title = stored.get("title")
        page_type = stored.get("type")
        observation_id = (
            stored.get("observation_id")
            or stored.get("observationId")
        )

        return BrowserContext(
            available=True,
            url=url if isinstance(url, str) else None,
            page=(
                None
                if title is None and page_type is None
                else BrowserPageContext(
                    title=title if isinstance(title, str) else None,
                    type=page_type if isinstance(page_type, str) else None,
                )
            ),
            observation_id=(
                observation_id
                if isinstance(observation_id, str)
                else None
            ),
        )

    @staticmethod
    def _default_capabilities() -> list[Capability]:
        return [
            Capability(
                name="git.read",
                available=True,
                authorized=False,
            ),
            Capability(
                name="state.read",
                available=True,
                authorized=False,
            ),
        ]

    @staticmethod
    def _build_evidence_quality(
        *,
        memory: MemoryContext,
        browser: BrowserContext,
        git: GitWslContext,
        tests: TestContext,
    ) -> EvidenceQuality:
        missing: list[str] = []
        stale: list[str] = []
        conflicts: list[str] = []

        if not memory.notes:
            missing.append("No matching durable memory notes were supplied.")

        if not browser.available:
            missing.append("No browser observation is available.")

        if git.sync_state == "UNKNOWN":
            missing.append("Git remote synchronization state is unknown.")

        if tests.status == "unknown":
            missing.append("No verified persisted test result is available.")

        overall = "strong"

        if missing:
            overall = "fair" if len(missing) <= 2 else "poor"

        return EvidenceQuality(
            overall=overall,
            missing=missing,
            stale=stale,
            conflicts=conflicts,
        )
