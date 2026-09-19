from __future__ import annotations

import os
import shutil
import subprocess
import sys


ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def test_response_line_break_mutation_breaks_real_chromium_seam() -> None:
    chrome = shutil.which("google-chrome-stable") or shutil.which("google-chrome") or shutil.which("chromium")
    chromedriver = shutil.which("chromedriver")
    if not chrome or not chromedriver:
        import pytest
        pytest.skip("real Chromium/ChromeDriver is not installed in this environment")

    env = dict(os.environ)
    env["PASI_E2E_MUTATION"] = "collapse_response_whitespace"
    result = subprocess.run(
        [sys.executable, "scripts/e2e_chromium_response_recovery.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode != 0, result.stdout + result.stderr
