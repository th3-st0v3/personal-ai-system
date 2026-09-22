#!/usr/bin/env python3
"""Run PASI's deterministic validation stack without paid provider/model usage."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_PROVIDER_KEYS = (
    "OPENROUTER_API_KEY",
    "PERPLEXITY_API_KEY",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "NVIDIA_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
)


def test_environment() -> dict[str, str]:
    env = dict(os.environ)
    env["PASI_FREE_TEST_MODE"] = "1"
    for key in SENSITIVE_PROVIDER_KEYS:
        env.pop(key, None)
    env.pop("PASI_BRIDGE_TOKEN", None)
    return env


def run(label: str, command: list[str], env: dict[str, str]) -> None:
    print(f"\n==> {label}", flush=True)
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"{label} failed with exit code {completed.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run PASI deterministic/local validation without paid provider usage."
    )
    parser.add_argument(
        "--core-only",
        action="store_true",
        help="Run repository validation but skip browser fixture acceptance.",
    )
    args = parser.parse_args()

    env = test_environment()
    run("Repository validation", ["bash", "scripts/check_all.sh"], env)

    if not args.core_only:
        run(
            "Chromium response-recovery fixture",
            [sys.executable, "scripts/e2e_chromium_response_recovery.py"],
            env,
        )
        run(
            "Chromium prompt/chaining fixture",
            [sys.executable, "scripts/e2e_chromium_prompt_submission.py"],
            env,
        )

    print("\nFREE VALIDATION PASSED: no paid provider/model credentials are available to the test process.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
