from __future__ import annotations

import hashlib
import re

PROMPT_PATTERN_VERSION = "2.2.0"
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
    """Compile a focused model-facing prompt for exactly one roadmap task."""
    task_text = _bounded_block(task, MAX_TASK_CHARS)
    if not task_text:
        raise ValueError("task must not be empty")

    recent = tuple(
        item for item in (_bounded_block(value, 600) for value in recent_tasks)
        if item
    )[-4:]
    roadmap = tuple(
        item for item in (_bounded_block(value, 600) for value in roadmap_tasks)
        if item
    )[:8]

    lines = [
        "PASi TASK EXECUTION MODE:",
        "The CURRENT TASK below is the only engineering objective for this operation.",
        "Do not replace it with a broader project, brainstorm, audit, or a generic improvement.",
        "Do not choose a different task. The runner owns task selection and will provide another task after this one is verified complete.",
        "",
        "CURRENT TASK:",
        task_text,
        "",
        "EXECUTE NOW:",
        "1. Inspect the relevant repository architecture, current implementation, tests, and recent changes.",
        "2. Implement the task's objective and every acceptance criterion; do not stop after a partial or cosmetic change.",
        "3. Run the task's stated verification plus targeted integration/runtime checks that are practical in this environment.",
        "4. If verification fails, diagnose the concrete failure, repair it, and rerun the failed check before declaring completion.",
        "5. Keep the change inside the task's stated scope. Do not spend this operation preparing the next roadmap task.",
        "",
        "IMPORTANT:",
        "The PASI_RESULT_* lines below are machine-readable reporting fields, not the task.",
        "Do not focus on them, optimize for them, or return them before the implementation and verification work is finished.",
        "Do not claim completion from a plan, source inspection, or a test you did not actually run.",
    ]

    if previous_failure.strip():
        lines.extend([
            "",
            "PREVIOUS FAILURE EVIDENCE — use this only to avoid repeating the same failed approach:",
            _bounded_block(previous_failure, MAX_FAILURE_CHARS),
        ])

    if roadmap:
        lines.extend([
            "",
            "ROADMAP CONTEXT — informational only; stay on CURRENT TASK:",
            *[f"- {item}" for item in roadmap],
        ])

    if recent:
        lines.extend([
            "",
            "RECENTLY COMPLETED TASKS — do not repeat them:",
            *[f"- {item}" for item in recent],
        ])

    lines.extend([
        "",
        "REPORT ONLY AFTER IMPLEMENTATION + VERIFICATION:",
        "Return each required marker exactly once.",
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
