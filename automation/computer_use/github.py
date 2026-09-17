from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from .adapters import ComputerAdapter, GitHubAdapter
from .contracts import ActionProposal, Observation


class GitHubAdapterError(RuntimeError):
    """Raised when the GitHub adapter cannot satisfy a semantic operation."""


class GitHubTransport(Protocol):
    """Connector/API seam for GitHub HTTP operations."""

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> Any: ...


@dataclass(frozen=True)
class UrllibGitHubTransport:
    """Bounded GitHub REST transport using an optional token from the environment."""

    api_base_url: str = "https://api.github.com"
    token: str | None = None
    timeout_seconds: float = 10.0
    max_response_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        parsed = urlsplit(self.api_base_url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("GitHub transport URL has an invalid port") from exc
        if parsed.scheme != "https" or parsed.hostname != "api.github.com" or port is not None and port != 443:
            raise ValueError("GitHub transport must target https://api.github.com")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("GitHub transport URL must not contain credentials")
        if self.timeout_seconds <= 0 or self.max_response_bytes <= 0:
            raise ValueError("transport bounds must be positive")

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> Any:
        if not path.startswith("/") or ".." in path.split("/"):
            raise GitHubAdapterError("GitHub API path is invalid")
        body = None
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "personal-ai-system",
        }
        token = self.token or os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if payload is not None:
            body = json.dumps(dict(payload)).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.api_base_url.rstrip('/')}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(self.max_response_bytes + 1)
        except HTTPError as exc:
            detail = exc.read(2_000).decode("utf-8", errors="replace")
            raise GitHubAdapterError(f"GitHub HTTP {exc.code}: {detail[:500]}") from exc
        except URLError as exc:
            raise GitHubAdapterError(f"GitHub request failed: {exc.reason}") from exc
        if len(raw) > self.max_response_bytes:
            raise GitHubAdapterError("GitHub response exceeded configured bound")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubAdapterError("GitHub returned invalid JSON") from exc


@dataclass
class GitHubControlAdapter(GitHubAdapter):
    """Provider-neutral GitHub boundary with API reads and an explicit UI fallback."""

    owner: str
    repository: str
    transport: GitHubTransport
    ui_adapter: ComputerAdapter | None = None
    session_id: str = "github"

    def __post_init__(self) -> None:
        if not self.owner.strip() or not self.repository.strip():
            raise ValueError("GitHub owner and repository are required")
        if "/" in self.owner or "/" in self.repository:
            raise ValueError("GitHub owner and repository must be single path segments")

    def observe(self) -> Observation:
        result = self._read("repository", {})
        return Observation(
            observation_id="github-repository",
            session_id=self.session_id,
            source="github-api",
            kind="github.repository",
            data=result,
        )

    def execute(self, action: ActionProposal) -> Observation:
        if action.action == "github_read":
            operation = action.parameters.get("operation", "repository")
            if not isinstance(operation, str):
                raise ValueError("GitHub read operation must be a string")
            parameters = action.parameters.get("parameters", {})
            if not isinstance(parameters, Mapping):
                raise ValueError("GitHub operation parameters must be an object")
            result = self._read(operation, parameters)
            return Observation(
                observation_id=f"github-{action.action_id}",
                session_id=action.session_id,
                source="github-api",
                kind=f"github.{operation}",
                data=result,
            )

        if action.action == "github_ui":
            if self.ui_adapter is None:
                raise GitHubAdapterError("GitHub UI fallback is not configured")
            if action.target not in {"github", "github.com"} and not action.target.startswith("github.com/"):
                raise GitHubAdapterError("GitHub UI action target is invalid")
            return self.ui_adapter.execute(action)

        raise GitHubAdapterError(f"unsupported GitHub action: {action.action}")

    def _read(self, operation: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
        path = self._path_for_operation(operation, parameters)
        result = self.transport.request("GET", path)
        if isinstance(result, Mapping):
            return dict(result)
        if isinstance(result, list):
            return {"items": result}
        raise GitHubAdapterError("GitHub API response must be an object or list")

    def _path_for_operation(self, operation: str, parameters: Mapping[str, Any]) -> str:
        root = f"/repos/{quote(self.owner, safe='')}/{quote(self.repository, safe='')}"
        if operation == "repository":
            return root
        if operation == "file":
            raw_path = parameters.get("path")
            if (
                not isinstance(raw_path, str)
                or not raw_path.strip()
                or raw_path.startswith("/")
                or ".." in raw_path.split("/")
            ):
                raise ValueError("GitHub file path must be repository-relative")
            return f"{root}/contents/{quote(raw_path, safe='/')}"
        if operation == "pulls":
            state = parameters.get("state", "open")
            if state not in {"open", "closed", "all"}:
                raise ValueError("GitHub pull request state is invalid")
            return f"{root}/pulls?state={quote(str(state), safe='')}&per_page=30"
        if operation == "issues":
            state = parameters.get("state", "open")
            if state not in {"open", "closed", "all"}:
                raise ValueError("GitHub issue state is invalid")
            return f"{root}/issues?state={quote(str(state), safe='')}&per_page=30"
        raise GitHubAdapterError(f"unsupported GitHub read operation: {operation}")


__all__ = [
    "GitHubAdapterError",
    "GitHubControlAdapter",
    "GitHubTransport",
    "UrllibGitHubTransport",
]
