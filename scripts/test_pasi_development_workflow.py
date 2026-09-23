from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pasi-development.yml"


def test_development_workflow_is_manual_and_has_control_modes() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source
    for mode in ("verify", "start-automation", "status", "stop"):
        assert f"          - {mode}" in source


def test_development_workflow_uses_self_hosted_verification_and_desktop_runner() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    verify = source[source.index("  verify:"):source.index("  desktop:")]
    assert "runs-on: [self-hosted, linux, x64, pasi-wsl]" in verify
    assert "bash scripts/check_fast.sh" in verify
    assert "runs-on: [self-hosted, linux, x64, pasi-desktop]" in source
    assert "scripts/pasi_desktop_preflight.py" in source
    assert "scripts/start_pasi_168h.sh --roadmap" in source
    assert "scripts/status_pasi_overnight.sh" in source
    assert "scripts/stop_pasi_overnight.sh" in source
    assert "ubuntu-latest" not in source


def test_development_workflow_validates_roadmap_scope() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "roadmap must remain inside the checked-out repository" in source
    assert "roadmap must be repository-relative" in source
