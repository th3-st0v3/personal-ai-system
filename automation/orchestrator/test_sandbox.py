from __future__ import annotations

import sys
from pathlib import Path

import pytest

from automation.orchestrator.sandbox_adapter import LocalBubblewrapSandbox
from automation.orchestrator.sandbox_schema import SandboxRequest


@pytest.fixture()
def sandbox_request() -> SandboxRequest:
    return SandboxRequest(
        request_id="req-1",
        task_id="task-1",
        step_id="step-1",
        actor_id="actor-1",
        argv=(sys.executable, "-c", "print('ok')"),
    )


def test_request_rejects_absolute_cwd() -> None:
    with pytest.raises(ValueError, match="relative path"):
        SandboxRequest(
            request_id="req-1",
            task_id="task-1",
            step_id="step-1",
            actor_id="actor-1",
            argv=("true",),
            cwd="/etc",
        )


def test_request_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        SandboxRequest(
            request_id="req-1",
            task_id="task-1",
            step_id="step-1",
            actor_id="actor-1",
            argv=("true",),
            timeout_seconds=301,
        )

    with pytest.raises(ValueError, match="max_output_bytes"):
        SandboxRequest(
            request_id="req-1",
            task_id="task-1",
            step_id="step-1",
            actor_id="actor-1",
            argv=("true",),
            max_output_bytes=0,
        )


def test_cwd_is_confined_to_root(tmp_path: Path, sandbox_request: SandboxRequest) -> None:
    sandbox = LocalBubblewrapSandbox(tmp_path)
    escaped = SandboxRequest(
        request_id=sandbox_request.request_id,
        task_id=sandbox_request.task_id,
        step_id=sandbox_request.step_id,
        actor_id=sandbox_request.actor_id,
        argv=sandbox_request.argv,
        cwd="..",
    )

    result = sandbox.execute(escaped)

    assert result.status == "rejected"
    assert result.error == "sandbox cwd escapes the configured root"


def test_missing_runtime_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sandbox_request: SandboxRequest,
) -> None:
    monkeypatch.setattr(
        "automation.orchestrator.sandbox_adapter.shutil.which",
        lambda _: None,
    )

    result = LocalBubblewrapSandbox(tmp_path).execute(sandbox_request)

    assert result.status == "rejected"
    assert result.request_id == sandbox_request.request_id
    assert result.task_id == sandbox_request.task_id
    assert result.step_id == sandbox_request.step_id
    assert result.error == "No supported local sandbox runtime is installed."


def test_local_runtime_executes_when_bubblewrap_is_usable(
    tmp_path: Path,
    sandbox_request: SandboxRequest,
) -> None:
    sandbox = LocalBubblewrapSandbox(tmp_path)
    probe = SandboxRequest(
        request_id=sandbox_request.request_id,
        task_id=sandbox_request.task_id,
        step_id=sandbox_request.step_id,
        actor_id=sandbox_request.actor_id,
        argv=("true",),
    )
    capability = sandbox.execute(probe)
    if capability.error == "No supported local sandbox runtime is installed.":
        pytest.skip("bubblewrap is not installed")
    if capability.status != "executed":
        pytest.skip(
            "bubblewrap is installed but this environment cannot run the required "
            f"isolation boundary: {capability.error or 'unknown error'}"
        )

    result = sandbox.execute(sandbox_request)

    assert result.status == "executed"
    assert result.return_code == 0
    assert result.stdout.strip() == "ok"
    assert result.metadata["output_truncated"] == "false"
