from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import quote

from automation.computer_use.github import GitHubAdapterError, GitHubTransport

COMMAND_MARKER = "<!-- PASI-AUTOMATION:v1 -->"
TITLE_PREFIX = "[PASI AUTOMATION]"
DEFAULT_MAX_COMMAND_CHARS = 16_000


@dataclass(frozen=True)
class AutomationCommand:
    issue_number: int
    actor: str
    prompt: str
    title: str


class GitHubCommandQueue:
    """Read-only, idempotent GitHub issue ingress for local automation."""

    def __init__(self, transport: GitHubTransport, owner: str, repository: str, *, allowed_actors: set[str], max_command_chars: int = DEFAULT_MAX_COMMAND_CHARS) -> None:
        if not owner.strip() or "/" in owner:
            raise ValueError("owner must be a single non-empty path segment")
        if not repository.strip() or "/" in repository:
            raise ValueError("repository must be a single non-empty path segment")
        if not allowed_actors:
            raise ValueError("allowed_actors must contain at least one GitHub login")
        if max_command_chars <= 0:
            raise ValueError("max_command_chars must be positive")
        self.transport = transport
        self.owner = owner
        self.repository = repository
        self.allowed_actors = {actor.strip().casefold() for actor in allowed_actors if actor.strip()}
        self.max_command_chars = max_command_chars
        if not self.allowed_actors:
            raise ValueError("allowed_actors must contain at least one non-empty GitHub login")

    @classmethod
    def from_environment(cls, transport: GitHubTransport) -> "GitHubCommandQueue":
        actors = {actor.strip() for actor in os.environ.get("PASI_GITHUB_COMMAND_ACTORS", "").split(",") if actor.strip()}
        return cls(
            transport,
            os.environ.get("PASI_GITHUB_OWNER", "th3-st0v3"),
            os.environ.get("PASI_GITHUB_REPOSITORY", "personal-ai-system"),
            allowed_actors=actors,
        )

    def poll_once(self, *, consumed_issue_numbers: set[int] | None = None) -> list[AutomationCommand]:
        consumed = consumed_issue_numbers or set()
        owner = quote(self.owner, safe="")
        repository = quote(self.repository, safe="")
        result = self.transport.request("GET", f"/repos/{owner}/{repository}/issues?state=open&sort=created&direction=asc&per_page=30")
        if not isinstance(result, list):
            raise GitHubAdapterError("GitHub issue queue response must be a list")
        commands: list[AutomationCommand] = []
        for item in result:
            command = self._parse_issue(item, consumed)
            if command is not None:
                commands.append(command)
        return commands

    def _parse_issue(self, item: Any, consumed: set[int]) -> AutomationCommand | None:
        if not isinstance(item, Mapping):
            return None
        raw_number = item.get("number")
        if not isinstance(raw_number, int) or isinstance(raw_number, bool) or raw_number in consumed:
            return None
        if "pull_request" in item:
            return None
        title = item.get("title")
        body = item.get("body")
        user = item.get("user")
        actor = user.get("login") if isinstance(user, Mapping) else None
        if not isinstance(title, str) or not title.startswith(TITLE_PREFIX):
            return None
        if not isinstance(body, str) or not body.startswith(COMMAND_MARKER):
            return None
        if not isinstance(actor, str) or actor.casefold() not in self.allowed_actors:
            return None
        prompt = body[len(COMMAND_MARKER):].strip()
        if not prompt or len(prompt) > self.max_command_chars:
            return None
        return AutomationCommand(issue_number=raw_number, actor=actor, prompt=prompt, title=title)


__all__ = ["AutomationCommand", "COMMAND_MARKER", "TITLE_PREFIX", "GitHubCommandQueue"]
