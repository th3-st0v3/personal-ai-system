from pathlib import Path

from automation.computer_use.capability_gateway import CapabilityGateway
from automation.computer_use.local_access import LocalAccessBroker


def test_gateway_dispatches_safe_system_and_file_reads(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    gateway = CapabilityGateway(LocalAccessBroker(tmp_path))

    system = gateway.dispatch({"request_id": "r1", "capability": "computer.system.read", "parameters": {}})
    assert system["status"] == "ok"
    assert system["data"]["read_only"] is True

    file_result = gateway.dispatch({
        "request_id": "r2",
        "capability": "computer.files.read",
        "parameters": {"path": "note.txt"},
    })
    assert file_result["status"] == "ok"
    assert file_result["data"]["content"] == "hello"


def test_gateway_rejects_unimplemented_write_and_command_capabilities(tmp_path: Path) -> None:
    gateway = CapabilityGateway(LocalAccessBroker(tmp_path))
    for capability in ("computer.files.write", "computer.command.execute", "computer.desktop.control"):
        result = gateway.dispatch({"request_id": capability, "capability": capability, "parameters": {}})
        assert result["status"] == "denied"


def test_gateway_requires_path_for_file_reads(tmp_path: Path) -> None:
    gateway = CapabilityGateway(LocalAccessBroker(tmp_path))
    result = gateway.dispatch({"request_id": "missing-path", "capability": "computer.files.read", "parameters": {}})
    assert result["status"] == "error"
    assert "parameters.path" in result["error"]


def test_gateway_preserves_request_id_on_safe_errors(tmp_path: Path) -> None:
    state_root = tmp_path / "operator-state"
    monkeypatch.setenv("PASI_STATE_ROOT", str(state_root))
    gateway = CapabilityGateway(LocalAccessBroker(tmp_path))
    result = gateway.dispatch({
        "request_id": "bad-file",
        "capability": "computer.files.read",
        "parameters": {"path": "missing.txt"},
    })
    assert result["status"] == "error"
    assert result["request_id"] == "bad-file"


def test_gateway_advertises_resource_acquisition_as_approval_gated(tmp_path: Path) -> None:
    gateway = CapabilityGateway(LocalAccessBroker(tmp_path))
    capability = next(item for item in gateway.capabilities() if item["name"] == "computer.resource.acquire")
    assert capability["risk"] == "approval_required"


def test_gateway_blocks_unapproved_resource_without_executing(tmp_path: Path, monkeypatch) -> None:
    gateway = CapabilityGateway(LocalAccessBroker(tmp_path))
    result = gateway.dispatch({
        "request_id": "resource-1",
        "capability": "computer.resource.acquire",
        "parameters": {"kind": "public_download", "url": "https://example.com/tool.bin"},
    })
    assert result["status"] == "blocked"
    assert result["risk"] == "approval_required"
    assert result["obstacle_id"]
    assert (state_root / "automation" / "action-list.md").exists()
