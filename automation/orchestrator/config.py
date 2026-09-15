from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_DIR = PROJECT_ROOT / ".ai"

FAILURES_DIR = AI_DIR / "failures"
SCREENSHOTS_DIR = AI_DIR / "screenshots"
TRACES_DIR = AI_DIR / "traces"
LOGS_DIR = AI_DIR / "logs"


@dataclass(frozen=True)
class RetryLimits:
    implementation_attempts: int = 2
    test_repair_attempts: int = 3
    browser_repair_attempts: int = 3
    ux_repair_attempts: int = 2
    security_repair_attempts: int = 2


@dataclass(frozen=True)
class OrchestratorConfig:
    project_root: Path = PROJECT_ROOT
    ai_dir: Path = AI_DIR

    max_conversation_chars: int = 120_000
    rollover_safety_margin_chars: int = 8_000

    chatgpt_timeout_seconds: int = 15 * 60

    retry_limits: RetryLimits = RetryLimits()


CONFIG = OrchestratorConfig()


def ensure_runtime_directories() -> None:
    """Create all local orchestration runtime directories."""
    for directory in (
        AI_DIR,
        FAILURES_DIR,
        SCREENSHOTS_DIR,
        TRACES_DIR,
        LOGS_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)