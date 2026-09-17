from datetime import datetime, timedelta, timezone
from typing import Any

from scripts.pasi_chat import controller_observation_is_live, route_chat


class FakeAdapter:
    def __init__(self, observation: dict[str, Any] | None):
        self.observation = observation
        self.new_sessions = 0
        self.reasoning = 0
        self.github = 0

    def read_browser_observation(self) -> dict[str, Any] | None:
        return self.observation

    def new_session(self) -> str:
        self.new_sessions += 1
        return f"new-chat-{self.new_sessions}"

    def attach_github_repository(self, repository: str) -> str:
        self.github += 1
        return f"github-{repository}"

    def select_reasoning_mode(self, mode: str) -> None:
        self.reasoning += 1


def state(url: str | None, *, exhausted: bool = False) -> dict[str, Any]:
    return {
        "schema_version": "test",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "kind": "chatgpt_state",
            "chat_url": url,
            "chat_exhausted": exhausted,
            "conversation_context_exhausted": exhausted,
            "github_attached": False,
        },
    }


def test_route_chat_preserves_known_chat_when_controller_temporarily_has_no_url() -> None:
    adapter = FakeAdapter(state(None))
    handoff: dict[str, object] = {
        "chat_url": "https://chatgpt.com/c/known",
        "chat_exhausted": False,
        "github_attached": False,
        "reasoning_mode": "thinking",
    }

    updated, chat_url = route_chat(adapter, handoff, "task", "th3-st0v3/personal-ai-system", "never")

    assert adapter.new_sessions == 0
    assert chat_url == "https://chatgpt.com/c/known"
    assert updated["chat_url"] == "https://chatgpt.com/c/known"


def test_route_chat_adopts_a_detected_new_chat_instead_of_creating_another() -> None:
    adapter = FakeAdapter(state("https://chatgpt.com/c/new"))
    handoff: dict[str, object] = {
        "chat_url": "https://chatgpt.com/c/old",
        "chat_exhausted": False,
        "github_attached": True,
        "reasoning_mode": "thinking",
    }

    updated, chat_url = route_chat(adapter, handoff, "task", "th3-st0v3/personal-ai-system", "never")

    assert adapter.new_sessions == 0
    assert adapter.reasoning == 1
    assert chat_url == "https://chatgpt.com/c/new"
    assert updated["chat_url"] == "https://chatgpt.com/c/new"
    assert updated["github_attached"] is False
    assert updated["reasoning_mode"] == "thinking"
    history = updated["chat_url_history"]
    assert isinstance(history, list) and history
    entry = history[-1]
    assert isinstance(entry, dict)
    assert entry["previous_url"] == "https://chatgpt.com/c/old"
    assert entry["new_url"] == "https://chatgpt.com/c/new"


def test_route_chat_creates_replacement_only_for_verified_exhaustion() -> None:
    adapter = FakeAdapter(state("https://chatgpt.com/c/exhausted", exhausted=True))
    handoff: dict[str, object] = {
        "chat_url": "https://chatgpt.com/c/exhausted",
        "chat_exhausted": False,
        "github_attached": False,
        "reasoning_mode": "thinking",
    }

    updated, chat_url = route_chat(adapter, handoff, "task", "th3-st0v3/personal-ai-system", "never")

    assert adapter.new_sessions == 1
    assert chat_url is None
    assert updated["chat_exhausted"] is False


def test_route_chat_does_not_replace_chat_for_a_nonexhaustion_load_failure() -> None:
    adapter = FakeAdapter(None)
    handoff: dict[str, object] = {
        "chat_url": "https://chatgpt.com/c/known",
        "chat_exhausted": False,
    }

    updated, chat_url = route_chat(adapter, handoff, "task", "th3-st0v3/personal-ai-system", "never")

    assert adapter.new_sessions == 0
    assert chat_url == "https://chatgpt.com/c/known"
    assert updated["chat_url"] == "https://chatgpt.com/c/known"


def test_route_chat_creates_initial_chat_when_nothing_is_known() -> None:
    adapter = FakeAdapter(state(None))
    handoff: dict[str, object] = {}

    updated, chat_url = route_chat(adapter, handoff, "task", "th3-st0v3/personal-ai-system", "never")

    assert adapter.new_sessions == 1
    assert chat_url is None
    assert updated["chat_exhausted"] is False


def test_controller_observation_live_contract_accepts_recent_state() -> None:
    now = datetime.now(timezone.utc)
    captured = (now - timedelta(seconds=2)).isoformat()
    observation = {"data": {"kind": "chatgpt_state", "captured_at": captured}}

    assert controller_observation_is_live(observation, now=now)


def test_controller_observation_live_contract_rejects_stale_state() -> None:
    now = datetime.now(timezone.utc)
    captured = (now - timedelta(seconds=30)).isoformat()
    observation = {"data": {"kind": "chatgpt_state", "captured_at": captured}}

    assert not controller_observation_is_live(observation, now=now)
