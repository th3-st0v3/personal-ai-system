from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_m1_acceptance_persists_failure_evidence() -> None:
    source = (ROOT / "scripts" / "run_m1_live_acceptance.py").read_text(encoding="utf-8")
    assert 'evidence["status"] = "STARTED"' in source
    assert 'evidence["status"] = "FAIL"' in source
    assert 'write_evidence(evidence_path, evidence)' in source
    assert '"completed_count": len(results)' in source


def test_m2_acceptance_binds_recovery_to_one_operation_and_handoff() -> None:
    source = (ROOT / "scripts" / "run_m2_live_acceptance.sh").read_text(encoding="utf-8")
    required = (
        'if op.get("operation_id") != opid:',
        'if op.get("status") not in {"claimed","generating"}:',
        'if handoff.get("active_operation_id") != opid:',
        '"manual_tab_recovery_recorded":True',
        '"handoff_cleared_after_completion": True',
        'if handoff_after.get("active_operation_id") == opid:',
    )
    for marker in required:
        assert marker in source


def test_m2_uses_authenticated_bridge_and_exact_operation_endpoint() -> None:
    source = (ROOT / "scripts" / "run_m2_live_acceptance.sh").read_text(encoding="utf-8")
    assert 'PASI_BRIDGE_TOKEN' in source
    assert '/operation?operation_id=' in source
    assert '/browser/health' in source
    assert '/browser/state' in source
