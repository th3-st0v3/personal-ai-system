from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_p04_evidence_assembler_requires_actual_deadline_completion() -> None:
    source = (ROOT / "scripts" / "capture_pasi_long_run_evidence.py").read_text(encoding="utf-8")
    assert 'if not deadline_reached:' in source
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

    pass_args = (EXPECTED_RUNTIME_SECONDS, True, "deadline_reached", 10, True, True, True)
    incomplete = classify_p04_status(EXPECTED_RUNTIME_SECONDS, False, "", 10, True, True, True)
    early_stop = classify_p04_status(EXPECTED_RUNTIME_SECONDS, True, "roadmap_complete", 10, True, True, True)
    manual_stop = classify_p04_status(EXPECTED_RUNTIME_SECONDS, True, "stopped", 10, True, True, True)
    passed = classify_p04_status(*pass_args)
    short_runtime = classify_p04_status(EXPECTED_RUNTIME_SECONDS - 60, True, "deadline_reached", 10, True, True, True)
    missing_resource = classify_p04_status(EXPECTED_RUNTIME_SECONDS, True, "deadline_reached", 0, True, True, True)
    dirty_worktree = classify_p04_status(EXPECTED_RUNTIME_SECONDS, True, "deadline_reached", 10, True, False, True)
    unverified_pr = classify_p04_status(EXPECTED_RUNTIME_SECONDS, True, "deadline_reached", 10, True, True, False)

    assert incomplete[0] == "INCOMPLETE"
    assert early_stop[0] == "FAIL"
    assert manual_stop[0] == "FAIL"
    assert passed[0] == "PASS"
    assert short_runtime[0] == "FAIL"
    assert missing_resource[0] == "FAIL"
    assert dirty_worktree[0] == "FAIL"
    assert unverified_pr[0] == "FAIL"

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
