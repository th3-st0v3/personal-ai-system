from pathlib import Path
import re


SCRIPT = Path("scripts/run_m2_live_acceptance.sh")


def test_m2_harness_uses_a_single_idempotent_operation_identity() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"idempotency_key": idempotency_key' in source
    assert '"operation_id") != p["operation_id"]' in source
    assert "idempotency_key" in source
    assert "operation identity changed during recovery" in source


def test_m2_harness_requires_exactly_one_browser_reclaim() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "retry_count == 1" in source
    assert "controller_retry_count == 1" in source
    assert "retry_count > 1" in source
    assert 'expected exactly one recovery/reclaim' in source


def test_m2_harness_requires_browser_reload_recovery_events() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'event.get("phase") == "reloading"' in source
    assert 'event.get("phase") == "preserve_current_chat"' in source
    assert '"recovery_events": op.get("recovery_events") or []' in source


def test_m2_harness_requires_exact_conversation_identity_and_single_delta() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "conversation identity changed during M2 recovery" in source
    assert "conversation signature delta was not exactly +1/+1" in source
    assert '"duplicate_user_message_delta":0' in source


def test_m2_harness_runs_all_three_restart_stages() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for stage in ("browser_reload_reclaimed_once", "bridge_restart_recovered", "runner_restart_resumed"):
        assert f'"{stage}"' in source
    assert re.search(r'bash scripts/start_pasi_168h.sh --resume', source)

def test_m2_harness_requires_runner_to_resume_the_same_persisted_operation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'Resuming persisted ChatGPT operation: {opid}' in source
    assert 'runner_log_path = Path(os.environ["RUNNER_LOG"])' in source
    assert 'initial_submit_count != 1' in source
    assert 'resume_count < 1' in source
    assert '"runner_resume_verified":True' in source

def test_m2_harness_passes_stamp_into_embedded_python() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"$PYTHON" - "$PROMPT" "$OUT" "$STAMP" <<\'PY\'' in source
    assert "prompt, out, stamp = sys.argv[1:]" in source
    assert '"completion_markers": [f"M2-LIVE-{stamp}"]' in source


def test_m2_harness_prompt_creates_a_real_generation_window() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "output the integers 1 through 1000, one integer per line" in source
    assert "end with exactly M2-LIVE-$STAMP on its own line" in source
