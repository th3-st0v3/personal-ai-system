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


def test_p04_status_is_strict_about_the_168_hour_deadline() -> None:
    from scripts.capture_pasi_long_run_evidence import EXPECTED_RUNTIME_SECONDS, classify_p04_status

    assert classify_p04_status(EXPECTED_RUNTIME_SECONDS, False, "") == "INCOMPLETE"
    assert classify_p04_status(EXPECTED_RUNTIME_SECONDS, True, "roadmap_complete") == "FAIL"
    assert classify_p04_status(EXPECTED_RUNTIME_SECONDS, True, "stopped") == "FAIL"
    assert classify_p04_status(EXPECTED_RUNTIME_SECONDS, True, "deadline_reached") == "PASS"
    assert classify_p04_status(EXPECTED_RUNTIME_SECONDS - 60, True, "deadline_reached") == "FAIL"


def test_resource_peak_summary_tracks_observed_peaks() -> None:
    from scripts.capture_pasi_long_run_evidence import resource_peak_summary

    report = resource_peak_summary(
        [
            {
                "processes": {
                    "runner": {"rss_kib": 100, "cpu_percent": 2.5},
                    "bridge": {"rss_kib": 40, "cpu_percent": 1.0},
                }
            },
            {
                "processes": {
                    "runner": {"rss_kib": 120, "cpu_percent": 4.5},
                    "bridge": {"rss_kib": 45, "cpu_percent": 1.5},
                }
            },
        ]
    )

    assert report["samples"] == 2
    assert report["processes"]["runner"]["peak_rss_kib"] == 120
    assert report["processes"]["runner"]["peak_cpu_percent"] == 4.5
    assert report["processes"]["bridge"]["peak_rss_kib"] == 45
