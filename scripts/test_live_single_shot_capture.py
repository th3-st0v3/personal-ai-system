from pathlib import Path
import subprocess


def test_live_capture_script_has_strict_single_shot_contract() -> None:
    path = Path("scripts/run_live_single_shot_capture.sh")
    source = path.read_text(encoding="utf-8")
    assert '"operation_type": "prompt"' in source
    assert "retry_count" in source
    assert "response_marker_verified" in source
    assert "conversation_delta_verified" in source
    assert "marker_satisfied" in source
    assert "generation_start_ms" in source


def test_live_capture_script_has_valid_shell_syntax() -> None:
    subprocess.run(["bash", "-n", "scripts/run_live_single_shot_capture.sh"], check=True)