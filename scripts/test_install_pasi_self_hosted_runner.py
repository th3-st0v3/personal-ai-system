from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_pasi_self_hosted_runner.sh"


def test_self_hosted_runner_installer_has_valid_shell_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_self_hosted_runner_installer_can_self_request_registration_token() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'gh auth status >/dev/null 2>&1' in source
    assert 'gh api --method POST "repos/${REPOSITORY}/actions/runners/registration-token" --jq .token' in source
    assert 'PASI_RUNNER_TOKEN is required unless authenticated gh CLI is available.' in source


def test_self_hosted_runner_installer_assigns_both_pasi_labels() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'RUNNER_LABELS="${PASI_RUNNER_LABELS:-pasi-desktop,pasi-wsl,pasi-capabilities-v1}"' in source
    assert '--labels "$RUNNER_LABELS"' in source


def test_self_hosted_runner_installer_does_not_persist_registration_token() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'unset RUNNER_TOKEN RELEASE_JSON TAG VERSION ARCHIVE URL' in source
    assert 'Registration token was not persisted' in source or 'token was not persisted' in source