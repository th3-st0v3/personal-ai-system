from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    command: list[str]
    return_code: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.return_code == 0


class GitManager:
    def __init__(self, project_root: Path):
        self.project_root = project_root

    def run(
        self,
        *args: str,
        timeout: int = 60,
    ) -> CommandResult:
        command = ["git", *args]

        process = subprocess.run(
            command,
            cwd=self.project_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

        return CommandResult(
            command=command,
            return_code=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
        )

    def status(self) -> CommandResult:
        return self.run("status", "--short")

    def current_branch(self) -> str | None:
        result = self.run(
            "branch",
            "--show-current",
        )

        if not result.success:
            return None

        branch = result.stdout.strip()

        return branch or None

    def head_commit(self) -> str | None:
        result = self.run(
            "rev-parse",
            "HEAD",
        )

        if not result.success:
            return None

        commit = result.stdout.strip()

        return commit or None

    def diff(self) -> CommandResult:
        return self.run("diff")

    def diff_stat(self) -> CommandResult:
        return self.run(
            "diff",
            "--stat",
        )

    def recent_commits(
        self,
        limit: int = 20,
    ) -> CommandResult:
        return self.run(
            "log",
            f"-{limit}",
            "--oneline",
        )