from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any, Protocol

from automation.computer_use.adapters import AIAdapter, ComputerAdapter, GitHubAdapter, IDEAdapter, ResearchAdapter
from automation.computer_use.browser_use_adapter import BrowserUseTaskAdapter
from automation.computer_use.contracts import ActionProposal, Observation


class CommandAdapter(Protocol):
    def execute_command(self, command: str) -> Observation: ...


class SemanticExecutor:
    """Translate authorized semantic actions into concrete adapter calls.

    This is the missing application execution seam between the generic runner
    and provider adapters. It performs no authorization itself; BackgroundWorker
    remains the single authorization boundary.
    """

    def __init__(
        self,
        *,
        ai: AIAdapter | None = None,
        ide: IDEAdapter | None = None,
        github: GitHubAdapter | None = None,
        research: ResearchAdapter | None = None,
        browser: BrowserUseTaskAdapter | None = None,
        desktop: ComputerAdapter | None = None,
        command: CommandAdapter | None = None,
    ) -> None:
        self.ai = ai
        self.ide = ide
        self.github = github
        self.research = research
        self.browser = browser
        self.desktop = desktop
        self.command = command

    def execute(self, action: ActionProposal) -> Observation:
        if action.action == "observe":
            if self.ide is None:
                raise RuntimeError("no IDE observation adapter is configured")
            return self.ide.observe()
        if action.action.startswith("ai_"):
            return self._execute_ai(action)
        if action.action.startswith("ide_"):
            return self._execute_ide(action)
        if action.action.startswith("github_"):
            if self.github is None:
                raise RuntimeError("no GitHub adapter is configured")
            return self.github.execute(action)
        if action.action.startswith("web_"):
            return self._execute_research(action)
        if action.action == "browser_task":
            if self.browser is None:
                raise RuntimeError("no Browser Use adapter is configured")
            task = action.parameters.get("task")
            if not isinstance(task, str):
                raise ValueError("browser_task requires a string task parameter")
            return asyncio.run(self.browser.run(task)).observation()
        if action.action == "desktop_ui":
            if self.desktop is None:
                raise RuntimeError("no desktop adapter is configured")
            return self.desktop.execute(action)
        raise ValueError(f"unsupported semantic action: {action.action}")

    def _execute_ai(self, action: ActionProposal) -> Observation:
        if self.ai is None:
            raise RuntimeError("no AI adapter is configured")
        if action.action == "ai_new_session":
            session_id = self.ai.new_session()
            return Observation(
                observation_id=f"ai-session:{session_id}",
                session_id=action.session_id,
                source="ai-adapter",
                kind="ai_session",
                data={"session_id": session_id, "provider": self.ai.provider},
            )
        if action.action == "ai_select_reasoning":
            mode = action.parameters.get("mode")
            if not isinstance(mode, str) or not mode.strip():
                raise ValueError("ai_select_reasoning requires a mode")
            self.ai.select_reasoning_mode(mode)
            return Observation(
                observation_id=f"ai-reasoning:{action.action_id}",
                session_id=action.session_id,
                source="ai-adapter",
                kind="ai_reasoning_mode",
                data={"mode": mode, "provider": self.ai.provider},
            )
        if action.action == "ai_submit_prompt":
            prompt = action.parameters.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError("ai_submit_prompt requires a non-empty prompt")
            operation_id = self.ai.submit_prompt(prompt)
            return Observation(
                observation_id=f"ai-operation:{action.action_id}",
                session_id=action.session_id,
                source="ai-adapter",
                kind="ai_prompt_submitted",
                data={"operation_id": operation_id, "provider": self.ai.provider},
            )
        if action.action == "ai_read_response":
            response = self.ai.read_response()
            return Observation(
                observation_id=f"ai-response:{response.response_id}",
                session_id=action.session_id,
                source="ai-adapter",
                kind="ai_response",
                data=asdict(response),
            )
        raise ValueError(f"unsupported AI action: {action.action}")

    def _execute_ide(self, action: ActionProposal) -> Observation:
        if action.action == "ide_command":
            if self.command is None:
                raise RuntimeError("no bounded command adapter is configured")
            command = action.parameters.get("command")
            if not isinstance(command, str) or not command.strip():
                raise ValueError("ide_command requires a command")
            return self.command.execute_command(command)
        if self.ide is None:
            raise RuntimeError("no IDE adapter is configured")
        if action.action == "ide_read":
            path = action.parameters.get("path")
            if not isinstance(path, str) or not path.strip():
                raise ValueError("ide_read requires a path")
            return self.ide.read_file(path)
        if action.action == "ide_search":
            query = action.parameters.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ValueError("ide_search requires a query")
            return self.ide.search(query)
        if action.action == "ide_diagnostics":
            return self.ide.diagnostics()
        raise ValueError(f"unsupported IDE action: {action.action}")

    def _execute_research(self, action: ActionProposal) -> Observation:
        if self.research is None:
            raise RuntimeError("no research adapter is configured")
        if action.action == "web_search":
            query = action.parameters.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ValueError("web_search requires a query")
            return self.research.search(query)
        if action.action == "web_read":
            source = action.parameters.get("source")
            if not isinstance(source, str) or not source.strip():
                raise ValueError("web_read requires a source URL")
            return self.research.read(source)
        raise ValueError(f"unsupported research action: {action.action}")


__all__ = ["CommandAdapter", "SemanticExecutor"]
