from pathlib import Path
import re
import subprocess


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
    assert 'event.get("phase") in {"preserve_current_chat", "resume_handoff"}' in source
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


def test_m2_harness_accepts_existing_chatgpt_tabs_without_creating_one() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "existing_tabs_no_create|race_existing_tabs_no_create" in source
    assert "existing tab accepted; zero-tab path must create exactly one" in source
    assert "selected_tab_id" in source
    assert "tab_provisioning_initial" in source
    assert "initial tab provisioning evidence" in source

def test_m2_harness_rejects_stale_browser_health_before_queueing() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'get_fresh_browser_health()' in source
    assert 'PREFLIGHT_STARTED_AT=' in source
    assert 'stale PASI browser health' in source
    assert 'before M2 operation queueing' in source
    assert 'reload the PASI extension in opera://extensions' in source
    assert source.index('get_fresh_browser_health()') < source.index('idempotency_key = "m2-"')


def test_m2_harness_preflight_is_single_instance_and_cleans_stale_state() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    cleanup = Path("scripts/m2_live_cleanup.sh").read_text(encoding="utf-8")
    assert "m2-live.lock" in source
    assert "flock -n 9" in source
    assert "scripts/m2_live_cleanup.sh" in source
    assert "PASI_M2_MANUAL_RELOAD_GATE: true" in cleanup
    assert "M2 cleanup: stale operation from an interrupted acceptance run" in cleanup
    assert "pasi_extended_runtime_entrypoint.py" in cleanup
    assert "--worktree $REPO_ROOT" in cleanup
    assert "run_m2_live_acceptance.sh" in cleanup


def test_m2_manual_gate_can_be_released_from_a_second_terminal() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    release = Path("scripts/release_m2_manual_reload_gate.sh").read_text(encoding="utf-8")
    assert "scripts/release_m2_manual_reload_gate.sh" in source
    assert "wait_for_manual_reload_release" in source
    assert "no Enter key is required" in source
    assert "manual-reload-gate/release" in release
    assert "PASI_M2_MANUAL_RELOAD_GATE: true" in release
    assert "manual_reload_gate_armed" in release
    assert "response_text_available" in release
    assert "armed before the original response was durably captured" in release
    assert "completion_markers" in release
    assert "configured completion marker" in release


def test_m2_harness_and_runtime_admin_scripts_have_valid_shell_syntax() -> None:
    for path in (
        SCRIPT,
        Path("scripts/m2_live_cleanup.sh"),
        Path("scripts/release_m2_manual_reload_gate.sh"),
    ):
        subprocess.run(["bash", "-n", str(path)], check=True)


def test_m2_harness_waits_through_watchdog_and_uses_safe_cleanup_argument_passing() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "local deadline=$((SECONDS + 45))" in source
    assert 'error: native tab provisioning did not produce a usable ChatGPT tab within 45 seconds' in source
    assert '"$PYTHON" - "$operation_id" <<\'PY\'' in source
    assert 'sys.argv[1]' in source
    assert 'op.get("response_text_available") is True' in source
    assert 'completion_markers = op.get("completion_markers") or []' in source
    assert 'response_has_marker' in source
    assert 'any(' in source
    assert '| "$PYTHON" -c \'import json,sys; print(json.dumps({"operation_id":sys.argv[1]' not in source


def test_native_controller_arms_m2_gate_only_after_response_capture() -> None:
    source = Path("automation/chromium/pasi-chatgpt/content.js").read_text(encoding="utf-8")
    early_arm = """          if (
            isM2ManualReloadGate(operation) &&
            (submission.verified || Number(submission?.timing?.user_messages_added || 0) > 0)
          ) {
            await armM2ManualReloadGate(operation, '', submission.timing || null);
            scheduleManualReloadGateMonitor();
          }
"""
    assert early_arm not in source
    assert source.count("await armM2ManualReloadGate(operation, response, browserTiming);") == 1


def test_native_controller_reconciles_stale_manual_gate_before_polling() -> None:
    source = Path("automation/chromium/pasi-chatgpt/content.js").read_text(encoding="utf-8")
    assert "async function reconcileStaleManualReloadGate()" in source
    assert "localStorage.removeItem(ACTIVE_KEY)" in source
    assert "['failed', 'cancelled'].includes(current.status)" in source
    assert "const cleared = await reconcileStaleManualReloadGate();" in source
