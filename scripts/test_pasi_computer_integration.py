from scripts import pasi_chat_guard as guard


def test_chat_protocol_exposes_search_and_keeps_high_risk_capabilities_hidden() -> None:
    prompt = guard.computer_protocol_prompt()
    assert "computer.system.read" in prompt
    assert "computer.files.list" in prompt
    assert "computer.files.read" in prompt
    assert "computer.files.search" in prompt
    assert "computer.files.write" not in prompt
    assert "computer.command.execute" not in prompt
    assert "computer.credentials.read" not in prompt
    assert "computer.financial.execute" not in prompt
