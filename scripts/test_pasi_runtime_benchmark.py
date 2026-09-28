from scripts.pasi_runtime_benchmark import build_events, run


def test_benchmark_fixture_has_twenty_clean_operations():
    events = build_events()
    assert len([event for event in events if event.get("kind") == "browser_timing"]) == 20


def test_benchmark_passes_all_contracts():
    result = run()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["runtime_metrics"]["completion_rate"] == 1.0
    assert result["runtime_metrics"]["repeated_task_numbers"] == 0


def test_benchmark_is_explicitly_not_a_live_browser_claim():
    result = run()
    assert result["case"]["synthetic"] is True
    assert result["case"]["live_browser_claim"] is False
    assert result["evidence_contract"]["event_source"] == "deterministic synthetic fixture"
