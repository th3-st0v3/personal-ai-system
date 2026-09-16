from __future__ import annotations

import unittest

from automation.computer_use.contracts import (
    AIResponse,
    ActionProposal,
    CompletionState,
    ContextPackage,
    ControlEvent,
    Observation,
    Session,
)
from automation.computer_use.controller import (
    ControlPlane,
    InvalidControlTransition,
)


class ControlPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = Session(
            session_id="session-1",
            task_id="task-1",
            project="personal-ai-system",
            allowed_applications=("vscode", "chatgpt", "github", "web", "claude"),
            workspace_root="/workspace/personal-ai-system",
            background=True,
        )
        self.control = ControlPlane(self.session)

    def test_lifecycle_allows_observe_plan_execute_verify_complete(self) -> None:
        for phase in ("observing", "planning", "executing", "verifying", "completed"):
            self.control.transition(phase)
        self.assertEqual(self.control.phase, "completed")

    def test_illegal_transition_is_rejected(self) -> None:
        with self.assertRaises(InvalidControlTransition):
            self.control.transition("completed")

    def test_safe_action_is_allowed(self) -> None:
        action = ActionProposal(
            action_id="a1",
            session_id="session-1",
            target="vscode",
            action="ide_diagnostics",
        )
        result = self.control.authorize(action)
        self.assertTrue(result.allowed)
        self.assertFalse(result.requires_human_approval)

    def test_consequential_action_requires_external_approval(self) -> None:
        action = ActionProposal(
            action_id="a2",
            session_id="session-1",
            target="github",
            action="github_ui",
        )
        result = self.control.authorize(action)
        self.assertFalse(result.allowed)
        self.assertTrue(result.requires_human_approval)
        self.assertEqual(self.control.phase, "awaiting_authorization")

        approved = self.control.authorize(action, external_human_approval=True)
        self.assertTrue(approved.allowed)

    def test_unknown_or_denied_capability_does_not_execute(self) -> None:
        action = ActionProposal(
            action_id="a3",
            session_id="session-1",
            target="desktop",
            action="desktop_ui",
        )
        result = self.control.authorize(action)
        self.assertFalse(result.allowed)
        self.assertEqual(result.risk, "approval_required")

    def test_action_from_other_session_is_rejected(self) -> None:
        action = ActionProposal(
            action_id="a4",
            session_id="other-session",
            target="web",
            action="web_search",
        )
        with self.assertRaises(ValueError):
            self.control.authorize(action)

    def test_completion_states_are_explicit(self) -> None:
        for state in (
            "generating",
            "quiet",
            "complete",
            "interrupted",
            "error",
            "timeout",
            "unknown",
        ):
            response = AIResponse(
                response_id=f"response-{state}",
                session_id="session-1",
                provider="chatgpt",
                operation_id="op-1",
                text="result" if state == "complete" else "",
                completion=state,
            )
            self.assertEqual(response.completion, state)

    def test_context_and_observation_fingerprints_are_stable(self) -> None:
        observation = Observation(
            observation_id="obs-1",
            session_id="session-1",
            source="vscode",
            kind="diagnostics",
            data={"count": 2},
            captured_at="2026-09-16T00:00:00+00:00",
        )
        context = ContextPackage(
            context_id="ctx-1",
            session_id="session-1",
            objective="fix simulator",
            evidence=({"observation": observation.fingerprint()},),
            source_fingerprints=(observation.fingerprint(),),
        )
        self.assertEqual(observation.fingerprint(), observation.fingerprint())
        self.assertEqual(context.fingerprint(), context.fingerprint())

    def test_events_are_scoped_to_session_and_serializable(self) -> None:
        event = ControlEvent(
            event_id="event-1",
            session_id="session-1",
            event_type="observation_captured",
            details={"source": "vscode"},
        )
        self.control.record_event(event)
        self.assertEqual(self.control.events[0].to_dict()["event_type"], "observation_captured")


if __name__ == "__main__":
    unittest.main()
