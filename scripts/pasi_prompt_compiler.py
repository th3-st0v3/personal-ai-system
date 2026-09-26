from __future__ import annotations

import hashlib
import re

PROMPT_PATTERN_VERSION = "2.1.0"
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
    roadmap_name: str = "",
    current_task_id: str = "",
    completed_task_count: int = 0,
    previous_task: str = "",
    previous_result: str = "",
) -> str:
    """Compile the model-facing prompt with durable roadmap/task continuity."""
    del run_id, branch, worktree, phase, recent_tasks, roadmap_tasks

    task_text = _bounded_block(task, MAX_TASK_CHARS)
    if not task_text:
        raise ValueError("task must not be empty")

    lines = [
        "CURRENT TASK:",
        task_text,
    ]

    if roadmap_name.strip() or current_task_id.strip():
        lines.extend([
            "",
            "ROADMAP CONTEXT:",
            f"ROADMAP SOURCE: {_bounded_block(roadmap_name, 200) or 'repository project roadmap'}",
            f"ROADMAP TASK ID: {_bounded_block(current_task_id, 200) or 'not provided'}",
            f"COMPLETED TASK COUNT: {max(0, int(completed_task_count))}",
        ])

    prior_task = _bounded_block(previous_task, MAX_TASK_CHARS)
    if prior_task and prior_task != task_text:
        lines.extend([
            "",
            "CONTINUATION STATE:",
            "PREVIOUSLY COMPLETED TASK:",
            prior_task,
        ])
        if previous_result.strip():
            lines.extend([
                "PREVIOUS TASK VERIFIED RESULT:",
                _bounded_block(previous_result, MAX_FAILURE_CHARS),
            ])

    lines.extend([
        "",
        "Work on this task until its acceptance criteria are met. Inspect the relevant code, make the smallest correct change, verify it, and repair any verification failure. Do not start another task.",
    ])
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
