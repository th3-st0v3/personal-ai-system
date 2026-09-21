from __future__ import annotations

import hashlib
import re
from typing import Sequence

PROMPT_PATTERN_VERSION = "1.1.0"
MAX_TASK_CHARS = 4000
MAX_FAILURE_CHARS = 12000
MAX_RECENT_TASKS = 12
MAX_ROADMAP_TASKS = 12


def _compact(value: object, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit]


def _bounded_block(value: object, limit: int) -> str:
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return text[:limit]


def _lines(values: Sequence[str], fallback: str = "- none recorded") -> str:
    cleaned = [_compact(value, MAX_TASK_CHARS) for value in values if _compact(value, MAX_TASK_CHARS)]
    return "\n".join(f"- {value}" for value in cleaned) if cleaned else fallback


def prompt_hash(prompt: str) -> str:
    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def prompt_hash(prompt: str) -> str:
    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _conditional_directive(phase: str, attempt: int, previous_failure: str) -> str:
    if previous_failure.strip():
        return (
            "RECOVERY RETRY MODE: Verify PREVIOUS FAILURE EVIDENCE before acting, "
            "then change the implementation strategy instead of replaying the failed path."
        )
    if int(attempt) > 1:
        return (
            "RETRY MODE: Re-inspect the current repository state and solve the remaining "
            "requirement without repeating an unsuccessful approach."
        )
    if str(phase).casefold().strip() == "automation":
        return (
            "AUTOMATION FIRST PASS: Prefer concrete reliability, continuity, recovery, "
            "and response-to-next-prompt latency reductions while preserving all control boundaries."
        )
    return (
        "ENGINEERING FIRST PASS: Prefer reproducible evidence and verification of the "
        "current requirement before expanding scope."
    )


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
    recent_tasks: Sequence[str] = (),
    roadmap_tasks: Sequence[str] = (),
    previous_failure: str = "",
) -> str:
    """Compile the minimal model-facing prompt for one bounded task.

    Runtime metadata, safety policy, roadmap selection, and continuation authority
    stay in the controller. The model receives only the current task plus bounded
    failure evidence when this is a retry.
    """
    del run_id, task_number, attempt, max_attempts, branch, worktree, phase
    del recent_tasks, roadmap_tasks

    task_text = _bounded_block(task, MAX_TASK_CHARS)
    if not task_text:
        raise ValueError("task must not be empty")

    lines = [
        "CURRENT TASK:",
        task_text,
    ]
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
