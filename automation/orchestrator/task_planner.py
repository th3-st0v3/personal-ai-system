from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from automation.computer_use.contracts import ActionProposal, ActionKind, ActionRisk, Observation, Session


class StructuredModelClient(Protocol):
    """Minimal provider-neutral model seam for strict structured planning."""

    def complete(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class PlannerDecision:
    action: ActionProposal | None
    stop_requested: bool = False
    reason: str = ""


class StructuredTaskPlanner:
    """Parse and validate a model proposal without granting execution authority.

    The model can suggest an action or request a stop, but the worker/control plane
    remains responsible for authorization, execution, and completion verification.
    """

    def __init__(self, session: Session, model: StructuredModelClient) -> None:
        self.session = session
        self.model = model

    def plan(self, observations: Sequence[Observation]) -> ActionProposal | None:
        decision = self.decide(observations)
        if decision.stop_requested:
            return None
        return decision.action

    def decide(self, observations: Sequence[Observation]) -> PlannerDecision:
        prompt = self._build_prompt(observations)
        raw = self.model.complete(prompt)
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
            if not isinstance(value.get(key), str) or not value[key].strip():
                raise ValueError(f"planner action field {key!r} is required")

        if value["session_id"] != self.session.session_id:
            raise ValueError("planner action belongs to a different control session")

        action_name = value["action"]
        if action_name not in _ACTION_KINDS:
            raise ValueError(f"planner proposed unknown action kind: {action_name!r}")

        parameters = value.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError("planner action parameters must be an object")

        reason = value.get("reason", "")
        if reason is not None and not isinstance(reason, str):
            raise ValueError("planner action reason must be a string")

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
                "data": dict(observation.data),
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


__all__ = ["PlannerDecision", "StructuredModelClient", "StructuredTaskPlanner"]
