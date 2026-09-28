from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .github_projects import GitHubGraphQLTransport, GitHubProjectError


@dataclass(frozen=True)
class UrllibGitHubGraphQLTransport(GitHubGraphQLTransport):
    """Bounded GraphQL transport for api.github.com using GITHUB_TOKEN."""

    endpoint: str = "https://api.github.com/graphql"
    token: str | None = None
    timeout_seconds: float = 10.0
    max_response_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        if self.endpoint != "https://api.github.com/graphql":
            raise ValueError("GitHub GraphQL transport must target https://api.github.com/graphql")
        if self.timeout_seconds <= 0 or self.max_response_bytes <= 0:
            raise ValueError("transport bounds must be positive")

    def execute(self, query: str, variables: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("GraphQL query must be non-empty")
        token = self.token or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise GitHubProjectError("GITHUB_TOKEN is required for GitHub Projects V2 mutations")
        payload = json.dumps({"query": query, "variables": dict(variables or {})}).encode("utf-8")
        request = Request(
            self.endpoint,
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "personal-ai-system",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(self.max_response_bytes + 1)
        except HTTPError as exc:
            detail = exc.read(2_000).decode("utf-8", errors="replace")
            raise GitHubProjectError(f"GitHub GraphQL HTTP {exc.code}: {detail[:500]}") from exc
        except URLError as exc:
            raise GitHubProjectError(f"GitHub GraphQL request failed: {exc.reason}") from exc
        if len(raw) > self.max_response_bytes:
            raise GitHubProjectError("GitHub GraphQL response exceeded configured bound")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubProjectError("GitHub GraphQL returned invalid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise GitHubProjectError("GitHub GraphQL response must be an object")
        return decoded


__all__ = ["UrllibGitHubGraphQLTransport"]
