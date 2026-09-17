from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from automation.computer_use.adapters import AIAdapter
from automation.computer_use.contracts import ActionProposal, Observation, Session


DEFAULT_MAX_PROMPT_CHARS = 64_000
DEFAULT_MAX_MODEL_OUTPUT_CHARS = 32_000
DEFAULT_MAX_PARAMETERS_CHARS = 16_000
DEFAULT_MAX_FIELD_CHARS = 2_000


class StructuredModelClient(Protocol):
    """Minimal provider-neutral model seam for strict structured planning."""

    def complete(self, prompt: str) -> str: ...


class AIAdapterModelClient:
    """Adapt an existing AIAdapter to the strict planner model seam."""

    def __init__(
        self,
        adapter: AIAdapter,
        *,
        poll_interval_seconds: float = 0.5,
        max_wait_seconds: float = 300.0,
        create_session: bool = True,
    ) -> None:
        if poll_interval_seconds <= 0 or max_wait_seconds <= 0:
            raise ValueError("model polling bounds must be positive")
        self.adapter = adapter
        self.poll_interval_seconds = poll_interval_seconds
        self.max_wait_seconds = max_wait_seconds
        self._session_created = not create_session

    def complete(self, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("prompt is required")
        if not self._session_created:
            self.adapter.new_session()
            self._session_created = True

        self.adapter.submit_prompt(prompt)
        started = time.monotonic()
        while True:
            response = self.adapter.read_response()
            if response.completion in {"complete", "error", "interrupted", "timeout"}:
                if response.completion != "complete":
                    raise RuntimeError(f"model completion state was {response.completion!r}")
                if not response.response_available:
                    raise RuntimeError("model completed without a response payload")
                return response.text
            if time.monotonic() - started >= self.max_wait_seconds:
                raise TimeoutError("structured planner model response exceeded configured timeout")
            time.sleep(self.poll_interval_seconds)


@dataclass(frozen=True)
class PlannerDecision:
    action: ActionProposal | None
    stop_requested: bool = False
    reason: str = ""


class StructuredTaskPlanner:
    """Parse and validate model proposals without granting execution authority."""

    def __init__(
        self,
        session: Session,
        model: StructuredModelClient,
        *,
        max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
        max_model_output_chars: int = DEFAULT_MAX_MODEL_OUTPUT_CHARS,
        max_parameters_chars: int = DEFAULT_MAX_PARAMETERS_CHARS,
    ) -> None:
        if max_prompt_chars <= 0 or max_model_output_chars <= 0 or max_parameters_chars <= 0:
            raise ValueError("planner bounds must be positive")
        self.session = session
        self.model = model
        self.max_prompt_chars = max_prompt_chars
        self.max_model_output_chars = max_model_output_chars
        self.max_parameters_chars = max_parameters_chars

    def plan(self, observations: Sequence[Observation]) -> ActionProposal | None:
        decision = self.decide(observations)
        if decision.stop_requested:
            return None
        return decision.action

    def decide(self, observations: Sequence[Observation]) -> PlannerDecision:
        prompt = self._build_prompt(observations)
        if len(prompt) > self.max_prompt_chars:
            raise ValueError("planner prompt exceeded configured bound")

        raw = self.model.complete(prompt)
        if len(raw) > self.max_model_output_chars:
            raise ValueError("planner model output exceeded configured bound")
        payload = self._parse_json(raw)
        if payload.get("stop") is True:
            return PlannerDecision(action=None, stop_requested=True, reason="model requested stop")
        if payload.get("stop") not in (False, None):
            raise ValueError("planner stop must be a boolean")

        action_value = payload.get("action")
        if not isinstance(action_value, dict):
            raise ValueError("planner response must contain an action object or stop=true")

        action = self._parse_action(action_value)
        return PlannerDecision(action=action, reason="model proposed next action")

    def _parse_action(self, value: dict[str, Any]) -> ActionProposal:
        required = ("action_id", "session_id", "target", "action")
        for key in required:
            item = value.get(key)
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"planner action field {key!r} is required")
            if len(item) > DEFAULT_MAX_FIELD_CHARS:
                raise ValueError(f"planner action field {key!r} exceeds configured bound")

        if value["session_id"] != self.session.session_id:
            raise ValueError("planner action belongs to a different control session")

        action_name = value["action"]
        if action_name not in _ACTION_KINDS:
            raise ValueError(f"planner proposed unknown action kind: {action_name!r}")

        parameters = value.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError("planner action parameters must be an object")
        encoded_parameters = json.dumps(
            parameters,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        if len(encoded_parameters) > self.max_parameters_chars:
            raise ValueError("planner action parameters exceeded configured bound")

        reason = value.get("reason", "")
        if reason is not None and not isinstance(reason, str):
            raise ValueError("planner action reason must be a string")
        if isinstance(reason, str) and len(reason) > DEFAULT_MAX_FIELD_CHARS:
            raise ValueError("planner action reason exceeds configured bound")

        risk = value.get("risk")
        if risk is not None and risk not in _ACTION_RISKS:
            raise ValueError(f"planner proposed invalid risk: {risk!r}")

        action = ActionProposal(
            action_id=value["action_id"],
            session_id=value["session_id"],
            target=value["target"],
            action=action_name,
            parameters=parameters,
            reason=reason or "",
            risk=risk,
        )
        action.effective_risk()
        return action

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("planner model returned empty output")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("planner model returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("planner model response must be a JSON object")
        return value

    def _build_prompt(self, observations: Sequence[Observation]) -> str:
        bounded_observations = [
            {
                "observation_id": observation.observation_id,
                "session_id": observation.session_id,
                "source": observation.source,
                "kind": observation.kind,
                "data": _bounded_data(observation.data),
                "captured_at": observation.captured_at,
            }
            for observation in observations[-16:]
        ]
        schema = {
            "stop": False,
            "action": {
                "action_id": "string",
                "session_id": self.session.session_id,
                "target": "string",
                "action": "one supported action kind",
                "parameters": {},
                "reason": "string",
                "risk": "safe | approval_required | denied",
            },
        }
        return json.dumps(
            {
                "task_id": self.session.task_id,
                "project": self.session.project,
                "objective": "propose exactly one next semantic action; never claim completion",
                "response_schema": schema,
                "observations": bounded_observations,
                "rules": [
                    "Return JSON only.",
                    "Never invent evidence, approvals, or completed work.",
                    "Use the exact session_id supplied above.",
                    "The caller will perform independent authorization and verification.",
                    "Use stop=true only when no next action can be proposed; stop does not mean the task is complete.",
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def _bounded_data(data: Any) -> Any:
    try:
        encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        encoded = repr(data)
    if len(encoded) <= DEFAULT_MAX_FIELD_CHARS:
        return data
    return encoded[:DEFAULT_MAX_FIELD_CHARS] + "...<truncated>"


_ACTION_KINDS: frozenset[str] = frozenset(
    {
        "observe",
        "ai_new_session",
        "ai_select_reasoning",
        "ai_submit_prompt",
        "ai_read_response",
        "ide_read",
        "ide_diagnostics",
        "ide_search",
        "ide_command",
        "github_read",
        "github_ui",
        "web_search",
        "web_read",
        "browser_task",
        "desktop_ui",
    }
)
_ACTION_RISKS: frozenset[str] = frozenset({"safe", "approval_required", "denied"})


__all__ = [
    "AIAdapterModelClient",
    "DEFAULT_MAX_FIELD_CHARS",
    "DEFAULT_MAX_MODEL_OUTPUT_CHARS",
    "DEFAULT_MAX_PARAMETERS_CHARS",
    "DEFAULT_MAX_PROMPT_CHARS",
    "PlannerDecision",
    "StructuredModelClient",
    "StructuredTaskPlanner",
]
