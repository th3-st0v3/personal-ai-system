from __future__ import annotations

import hashlib
import re

PROMPT_PATTERN_VERSION = "2.0.0"
MAX_TASK_CHARS = 4000
MAX_FAILURE_CHARS = 12000


def _bounded_block(value: object, limit: int) -> str:
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return text[:limit]


def prompt_hash(prompt: str) -> str:
    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def compile_task_prompt(
    task: str,
    *,
    run_id: str,
    task_number: int,
    attempt: int,
    max_attempts: int,
    branch: str,
    worktree: str,
    phase: str,
    recent_tasks: tuple[str, ...] | list[str] = (),
    roadmap_tasks: tuple[str, ...] | list[str] = (),
    previous_failure: str = "",
) -> str:
    """Compile the minimal model-facing prompt for exactly one task."""
    del run_id, task_number, attempt, max_attempts, branch, worktree, phase
    del recent_tasks, roadmap_tasks

    task_text = _bounded_block(task, MAX_TASK_CHARS)
    if not task_text:
        raise ValueError("task must not be empty")

    lines = ["CURRENT TASK:", task_text]
    if previous_failure.strip():
        lines.extend([
            "",
            "PREVIOUS FAILURE EVIDENCE:",
            _bounded_block(previous_failure, MAX_FAILURE_CHARS),
        ])

    lines.extend([
        "",
        "RESULT:",
        "PASI_RESULT_STATUS: complete|needs_revision|blocked",
        "PASI_RESULT_SUMMARY: one concise sentence",
        "PASI_RESULT_REQUIREMENTS: complete",
        "PASI_RESULT_LIMITATIONS: handled|none|not_applicable",
        "PASI_RESULT_RESEARCH: performed|not_applicable",
        "PASI_RESULT_UX: verified|not_applicable",
        "PASI_RESULT_BACKEND: verified|not_applicable",
        "PASI_RESULT_EVIDENCE: concise tests/verification evidence",
        "PASI_RESULT_REPOSITORY_PROGRESS: changed|stopped",
        "PASI_RESULT_ALLOW_DELETE: true|false",
        "PASI_RESULT_PATCH_BEGIN",
        "<one unified git diff>",
        "PASI_RESULT_PATCH_END",
    ])
    return "\n".join(lines) + "\n"
