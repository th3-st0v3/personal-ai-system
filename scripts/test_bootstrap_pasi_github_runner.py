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
    assert "PASI_GITHUB_RUNNER_FORCE_RECONFIGURE" in source
    assert "sudo ./svc.sh stop" in source
    assert "sudo ./svc.sh uninstall" in source
    assert '[[ -d /run/systemd/system ]]' in source
    assert '-f "$RUNNER_DIR/.service"' in source
    assert "sudo ./svc.sh install" in source
    assert "sudo ./svc.sh start" in source
    assert "sudo ./svc.sh status" in source


def test_authoritative_workflow_uses_hosted_runner() -> None:
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "runs-on: ubuntu-latest" in workflow
    assert "[self-hosted, linux, x64, pasi-wsl]" not in workflow
    assert "check_fast.sh" in workflow
    assert "mode:" in workflow
    assert "fast" in workflow
    assert "live" in workflow


def test_standard_ci_and_security_use_hosted_runners_and_fork_safe() -> None:
    test_workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    security_workflow = (ROOT / ".github" / "workflows" / "pasi-security-analysis.yml").read_text(encoding="utf-8")
    assert "runs-on: ubuntu-latest" in test_workflow
    assert "[self-hosted, linux, x64, pasi-wsl]" not in test_workflow
    assert "runs-on: ubuntu-latest" in security_workflow
    assert "[self-hosted, linux, x64, pasi-wsl]" not in security_workflow
    assert "untrusted fork pull requests" in test_workflow
    assert "github.event.pull_request.head.repo.full_name == github.repository" in security_workflow


def test_development_and_branch_hygiene_validation_uses_intended_runner_boundaries() -> None:
    development = (ROOT / ".github" / "workflows" / "pasi-development.yml").read_text(encoding="utf-8")
    branch_hygiene = (ROOT / ".github" / "workflows" / "branch-hygiene.yml").read_text(encoding="utf-8")
    development_verify = development[development.index("  verify:"):development.index("  desktop:")]
    development_desktop = development[development.index("  desktop:"):]

    assert "runs-on: ubuntu-latest" in development_verify
    assert "runs-on: [self-hosted, linux, x64, pasi-desktop]" in development_desktop
    assert development_desktop.count("runs-on: [self-hosted, linux, x64, pasi-desktop]") == 1
    assert "runs-on: ubuntu-latest" in branch_hygiene
    assert branch_hygiene.count("runs-on: ubuntu-latest") == 2


def test_obsolete_hosted_pr_audits_are_not_present() -> None:
    assert not (ROOT / ".github" / "workflows" / "agent-impact-audit.yml").exists()
    assert not (ROOT / ".github" / "workflows" / "self-modification-boundary-audit.yml").exists()


def test_security_runs_cancel_stale_heads() -> None:
    workflow = (ROOT / ".github" / "workflows" / "pasi-security-analysis.yml").read_text(encoding="utf-8")
    assert "group: pasi-security-" in workflow
    assert "github.event.pull_request.number" in workflow
    assert "cancel-in-progress: true" in workflow


def test_fast_validator_exists_and_stays_free_of_live_acceptance_scripts() -> None:
    script = (ROOT / "scripts" / "check_fast.sh").read_text(encoding="utf-8")
    assert "python -m pytest -q" in script
    assert "node --test" in script
    assert "scripts/e2e_chromium_response_recovery.py" not in script
    assert "scripts/e2e_chromium_prompt_submission.py" not in script
