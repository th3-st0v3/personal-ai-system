from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_status_command_surfaces_resource_telemetry() -> None:
    source = (ROOT / "scripts" / "status_pasi_overnight.sh").read_text(encoding="utf-8")
    assert '"PASI resource telemetry|' in source
    assert 'resource-samples.jsonl' in source
    assert 'Resource evidence:' in source
