from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_without_pythonpath(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, script, *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_pasi_setup_entrypoint_is_import_safe_without_pythonpath() -> None:
    result = _run_without_pythonpath("scripts/pasi_setup.py", "--help")
    assert result.returncode == 0, result.stderr


def test_provider_router_entrypoint_is_import_safe_without_pythonpath() -> None:
    result = _run_without_pythonpath("scripts/pasi_provider_router.py", "--list-providers")
    assert result.returncode == 0, result.stderr
