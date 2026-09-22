from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pasi-development.yml"


def test_development_workflow_is_manual_and_has_control_modes() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source
    for mode in ("verify", "start-automation", "status", "stop"):
        assert f"          - {mode}" in source


def test_development_workflow_uses_desktop_runner_for_live_automation() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "runs-on: [self-hosted, linux, x64, pasi-desktop]" in source
    assert "scripts/pasi_desktop_preflight.py" in source
    assert "scripts/start_pasi_168h.sh --roadmap" in source
    assert "scripts/status_pasi_overnight.sh" in source
    assert "scripts/stop_pasi_overnight.sh" in source


def test_development_workflow_runs_verification_on_self_hosted_ci_runner() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    verify = source[source.index("  verify:"):source.index("  desktop:")]
    assert "runs-on: [self-hosted, linux, x64, pasi-wsl]" in verify
    assert "bash scripts/check_all.sh" in verify
    for suite in ("test_extension.js", "test_recovery.js", "test_native_mutation.js", "test_dom_fixtures.js"):
        assert f"automation/chromium/pasi-chatgpt/{suite}" in verify


def test_development_workflow_validates_roadmap_scope() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "roadmap must remain inside the checked-out repository" in source
    assert "roadmap must be repository-relative" in source
