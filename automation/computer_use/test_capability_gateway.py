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
    gateway = CapabilityGateway(LocalAccessBroker(tmp_path))
    result = gateway.dispatch({
        "request_id": "bad-file",
        "capability": "computer.files.read",
        "parameters": {"path": "missing.txt"},
    })
    assert result["status"] == "error"
    assert result["request_id"] == "bad-file"
