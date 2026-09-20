from __future__ import annotations

import subprocess
import sys


ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def test_response_line_break_mutation_breaks_native_extraction_seam() -> None:
    result = subprocess.run(
        [
            "node",
            "--test",
            "automation/chromium/pasi-chatgpt/test_native_mutation.js",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
