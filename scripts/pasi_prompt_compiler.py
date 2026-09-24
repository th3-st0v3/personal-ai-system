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
    task_id: str = "",
    recent_tasks: tuple[str, ...] | list[str] = (),
    roadmap_tasks: tuple[str, ...] | list[str] = (),
    previous_failure: str = "",
) -> str:
    """Compile a focused model-facing prompt for exactly one roadmap task."""
    task_text = _bounded_block(task, MAX_TASK_CHARS)
    if not task_text:
        raise ValueError("task must not be empty")

    lines = [
        "PASI TASK EXECUTION MODE:",
        "The CURRENT TASK below is the only engineering objective for this operation.",
        "Do not replace it with a broader project, brainstorm, audit, or generic improvement.",
        "Do not choose a different task. The deterministic PASI scheduler owns task selection.",
        "Use as many implementation and verification steps as necessary inside this one operation.",
        "",
    ]
    task_id = _bounded_block(task_id, 160)
    if task_id:
        lines.extend(["TASK ID:", task_id, ""])

    lines.extend([
        "CURRENT TASK:",
        task_text,
        "",
        "EXECUTE NOW:",
        "1. Inspect the relevant repository architecture, current implementation, tests, and recent changes.",
        "2. Implement the objective and every acceptance criterion contained in CURRENT TASK.",
        "3. Run the stated verification plus targeted integration/runtime checks that are practical in this environment.",
        "4. If verification fails, diagnose the concrete failure, repair it, and rerun the failed check.",
        "5. Continue until the acceptance criteria are actually satisfied. A plan, partial edit, single passing test, or status report is not completion.",
        "6. Keep the change inside CURRENT TASK scope. Do not prepare the next roadmap task.",
        "",
        "REPORTING PROTOCOL — NOT THE ENGINEERING OBJECTIVE:",
        "The PASI_RESULT_* lines below are machine-readable output syntax only.",
        "Do not optimize for these markers, stop to discuss them, or emit them before implementation and verification are finished.",
        "Do not claim completion from source inspection or unexecuted tests.",
    ])

    if previous_failure.strip():
        lines.extend([
            "",
            "PREVIOUS FAILURE EVIDENCE:",
            _bounded_block(previous_failure, MAX_FAILURE_CHARS),
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
