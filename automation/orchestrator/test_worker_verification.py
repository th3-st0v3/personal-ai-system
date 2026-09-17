from __future__ import annotations

from automation.computer_use.contracts import ActionProposal, Observation
from automation.orchestrator.worker_verification import verify_worker_observation


def make_action() -> ActionProposal:
    return ActionProposal("a1", "session-1", "test", "github_read")


def make_observation(*, session_id: str = "session-1", observation_id: str = "obs-1", source: str = "test", kind: str = "result") -> Observation:
    return Observation(
        observation_id=observation_id,
        session_id=session_id,
        source=source,
        kind=kind,
        data={"ok": True},
    )


def test_matching_observation_is_verified() -> None:
    verification = verify_worker_observation(make_action(), make_observation())

    assert verification.status == "verified"
    assert verification.verified is True
    assert verification.failures == ()
    assert "session match" in verification.checks
    assert "observation fingerprint" in verification.checks


def test_session_mismatch_fails() -> None:
    verification = verify_worker_observation(
        make_action(), make_observation(session_id="other-session")
    )

    assert verification.status == "failed"
    assert verification.verified is False
    assert "observation session does not match action session" in verification.failures


def test_empty_observation_metadata_fails() -> None:
    verification = verify_worker_observation(
        make_action(), make_observation(observation_id="", source="", kind="")
    )

    assert verification.status == "failed"
    assert len(verification.failures) == 3
    assert "observation observation_id is empty" in verification.failures
    assert "observation source is empty" in verification.failures
    assert "observation kind is empty" in verification.failures
