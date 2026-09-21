from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pasi-development.yml"


def test_development_workflow_is_manual_and_has_control_modes() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source
    for mode in ("verify", "start-automation", "status", "stop"):
        assert f"          - {mode}" in source


def test_development_workflow_uses_hosted_and_desktop_runners() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "runs-on: ubuntu-latest" in source
    assert "runs-on: [self-hosted, linux, x64, pasi-desktop]" in source


def test_development_workflow_controls_existing_pasi_launcher() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/pasi_desktop_preflight.py" in source
    assert "scripts/start_pasi_168h.sh --roadmap" in source
    assert "scripts/status_pasi_overnight.sh" in source
    assert "scripts/stop_pasi_overnight.sh" in source


def test_development_workflow_keeps_roadmap_inside_repository() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "roadmap must be repository-relative" in source
    assert "roadmap JSON valid" in source
