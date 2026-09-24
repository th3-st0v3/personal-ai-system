from scripts import pasi_chat_guard as guard


def test_chat_protocol_is_minimal_and_keeps_high_risk_capabilities_hidden() -> None:
    prompt = guard.computer_protocol_prompt()
    assert "LOCAL EVIDENCE REQUEST" in prompt
    assert "PASI_COMPUTER_REQUEST_BEGIN" in prompt
    assert "computer.files.search" in prompt
    assert "computer.files.write" not in prompt
    assert "computer.command.execute" not in prompt
    assert "computer.credentials.read" not in prompt
    assert "computer.financial.execute" not in prompt
    assert "Each request is executed by PASI" not in prompt
    assert "Maximum capability rounds per task" not in prompt
