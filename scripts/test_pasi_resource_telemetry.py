from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_resource_sampler_writes_run_scoped_jsonl() -> None:
    source = (ROOT / "scripts" / "pasi_resource_telemetry.py").read_text(encoding="utf-8")
    assert 'output = runtime_dir / "resource-samples.jsonl"' in source
    assert '"run_id": run_id' in source
    assert '"processes": {' in source
    assert 'os.fsync(handle.fileno())' in source


def test_resource_sampler_handles_managed_process_disappearance() -> None:
    source = (ROOT / "scripts" / "pasi_resource_telemetry.py").read_text(encoding="utf-8")
    assert 'return {"pid": pid, "status": "not_running"}' in source
    assert '"runner": runtime_dir / "runner.pid"' not in source


def test_resource_sampler_enforces_bounded_retention() -> None:
    source = (ROOT / "scripts" / "pasi_resource_telemetry.py").read_text(encoding="utf-8")
    assert "MAX_SAMPLE_FILE_BYTES = 16 * 1024 * 1024" in source
    assert "MAX_RETAINED_SAMPLES = 25_000" in source
    assert 'if args.interval < 5.0:' in source
