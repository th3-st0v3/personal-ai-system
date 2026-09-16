from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .browser_challenge import BrowserChallenge, detect_browser_challenge, mark_waiting_human
from .contracts import ActionProposal, Observation


class BrowserUseUnavailable(RuntimeError):
    """Raised when the optional browser-use dependency is not installed."""


class BrowserUseAdapterError(RuntimeError):
    """Raised when the Browser Use adapter cannot complete its bounded task."""


@dataclass(frozen=True)
class BrowserRunResult:
    session_id: str
    status: str
    result_text: str = ""
    url: str = ""
    title: str = ""
    challenge: BrowserChallenge | None = None

    def observation(self) -> Observation:
        data: dict[str, Any] = {
            "status": self.status,
            "result_text": self.result_text[:8000],
            "url": self.url,
            "title": self.title,
        }
        if self.challenge is not None:
            data["challenge"] = self.challenge.to_dict()
        return Observation(
            observation_id=f"browser-run:{self.session_id}",
            session_id=self.session_id,
            source="browser-use",
            kind="browser_run",
            data=data,
        )


@dataclass
class BrowserUseTaskAdapter:
    """Optional Browser Use integration with explicit human challenge handoff."""

    session_id: str
    llm_factory: Callable[[], Any]
    browser_factory: Callable[[], Any] | None = None
    max_steps: int = 40
    max_task_chars: int = 8_000
    background: bool = True

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id is required")
        if self.max_steps <= 0 or self.max_task_chars <= 0:
            raise ValueError("browser task bounds must be positive")

    async def run(self, task: str) -> BrowserRunResult:
        if not task.strip():
            raise ValueError("task is required")
        if len(task) > self.max_task_chars:
            raise BrowserUseAdapterError("browser task exceeds configured bound")

        try:
            from browser_use import Agent, Browser  # pyright: ignore[reportMissingImports]
        except ImportError as exc:
            raise BrowserUseUnavailable(
                "browser-use is optional; install requirements-browser.txt to enable it"
            ) from exc

        browser = self.browser_factory() if self.browser_factory is not None else Browser(
            headless=self.background
        )
        llm = self.llm_factory()
        challenge_holder: dict[str, BrowserChallenge] = {}

        async def detect_challenge(agent: Any) -> None:
            try:
                url = await agent.browser_session.get_current_page_url()
                title = await agent.browser_session.get_current_page_title()
                page = await agent.browser_session.get_current_page()
                text = ""
                if page is not None:
                    try:
                        text_value = await page.evaluate(
                            "() => document.body ? document.body.innerText : ''"
                        )
                        text = text_value if isinstance(text_value, str) else ""
                    except Exception:
                        text = ""
                challenge = detect_browser_challenge(
                    url=url or "",
                    title=title or "",
                    text=text,
                    session_id=self.session_id,
                )
                if challenge is not None:
                    challenge_holder["challenge"] = mark_waiting_human(challenge)
            except Exception:
                return

        async def should_stop() -> bool:
            return "challenge" in challenge_holder

        guarded_task = (
            "Perform the requested browser task using only information and controls "
            "available through the browser. If you encounter a CAPTCHA, Cloudflare, "
            "Turnstile, login gate, or other challenge/interstitial, stop immediately "
            "and report that a human must complete it. Do not bypass, solve, extract "
            "tokens from, disable, or evade any security challenge.\n\n"
            f"Task: {task}"
        )

        try:
            agent = Agent(
                task=guarded_task,
                llm=llm,
                browser=browser,
                register_should_stop_callback=should_stop,
            )
            history = await agent.run(
                max_steps=self.max_steps,
                on_step_start=detect_challenge,
            )
        except Exception as exc:
            challenge = challenge_holder.get("challenge")
            if challenge is not None:
                return BrowserRunResult(
                    session_id=self.session_id,
                    status="challenge_required",
                    url=challenge.url,
                    title=challenge.title,
                    challenge=challenge,
                )
            raise BrowserUseAdapterError(f"Browser Use task failed: {exc}") from exc

        challenge = challenge_holder.get("challenge")
        if challenge is not None:
            return BrowserRunResult(
                session_id=self.session_id,
                status="challenge_required",
                url=challenge.url,
                title=challenge.title,
                challenge=challenge,
            )

        result_text = ""
        try:
            result_text = str(history.final_result() or "")
        except Exception:
            pass

        url = ""
        title = ""
        try:
            url = await agent.browser_session.get_current_page_url() or ""
            title = await agent.browser_session.get_current_page_title() or ""
        except Exception:
            pass

        return BrowserRunResult(
            session_id=self.session_id,
            status="succeeded",
            result_text=result_text[:8000],
            url=url,
            title=title,
        )

    async def execute_authorized(
        self,
        action: ActionProposal,
        *,
        approval_granted: bool,
    ) -> BrowserRunResult:
        """Execute only an explicitly approved browser_task action."""
        if action.session_id != self.session_id:
            raise ValueError("action belongs to a different session")
        if action.action != "browser_task":
            raise ValueError("BrowserUseTaskAdapter only handles browser_task actions")
        if not approval_granted:
            raise PermissionError("browser_task requires external human approval")
        task = action.parameters.get("task")
        if not isinstance(task, str):
            raise ValueError("browser_task action requires a string task parameter")
        return await self.run(task)
