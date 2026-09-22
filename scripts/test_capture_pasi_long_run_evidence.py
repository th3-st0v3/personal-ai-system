from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_p04_evidence_assembler_requires_actual_deadline_completion() -> None:
    source = (ROOT / "scripts" / "capture_pasi_long_run_evidence.py").read_text(encoding="utf-8")
    assert 'if not deadline_reached:' in source
    assert 'elif stop_reason != "deadline_reached":' in source
    assert 'EXPECTED_RUNTIME_SECONDS = 168 * 60 * 60' in source


def test_p04_evidence_contains_required_provenance_sections() -> None:
    source = (ROOT / "scripts" / "capture_pasi_long_run_evidence.py").read_text(encoding="utf-8")
    for marker in (
        '"runtime_telemetry":',
        '"failure_provenance":',
        '"git": git',
        '"pr": pr',
        '"resources":',
        '"limitations": limitations',
    ):
        assert marker in source
