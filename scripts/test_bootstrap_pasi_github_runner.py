from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runner_bootstrap_has_no_baked_registration_token() -> None:
    source = (ROOT / "scripts" / "bootstrap_pasi_github_runner.sh").read_text(encoding="utf-8")
    assert "PASI_GITHUB_RUNNER_TOKEN" in source
    assert "--token" in source
    assert "<fresh repository runner registration token>" not in source
    assert "pasi-wsl,pasi-desktop,pasi-capabilities-v1" in source


def test_runner_bootstrap_is_noninteractive_and_service_aware() -> None:
    source = (ROOT / "scripts" / "bootstrap_pasi_github_runner.sh").read_text(encoding="utf-8")
    assert "--unattended" in source
    assert "--replace" in source
    assert "systemctl is-system-running" in source
    assert "sudo ./svc.sh install" in source
    assert "sudo ./svc.sh start" in source
    assert "sudo ./svc.sh status" in source


def test_authoritative_workflow_does_not_use_hosted_runner() -> None:
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "ubuntu-latest" not in workflow
    assert "self-hosted" in workflow
    assert "pasi-wsl" in workflow


def test_authoritative_ci_stays_self_hosted_and_fork_safe() -> None:
    test_workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    security_workflow = (ROOT / ".github" / "workflows" / "pasi-security-analysis.yml").read_text(encoding="utf-8")
    assert "ubuntu-latest" not in test_workflow
    assert "ubuntu-latest" not in security_workflow
    assert "runs-on: [self-hosted, linux, x64, pasi-wsl]" in test_workflow
    assert "runs-on: [self-hosted, linux, x64, pasi-wsl]" in security_workflow
    assert "untrusted fork pull requests" in test_workflow
    assert "github.event.pull_request.head.repo.full_name == github.repository" in security_workflow
