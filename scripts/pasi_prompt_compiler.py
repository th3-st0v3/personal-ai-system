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
    """Compile the smallest model-facing task prompt.

    Scheduler/runtime metadata remains controller-owned. It is intentionally not
    repeated in the model prompt; only the current task and bounded retry evidence
    cross the model boundary.
    """
    del run_id, task_number, attempt, max_attempts, branch, worktree, phase, recent_tasks, roadmap_tasks

    task_text = _bounded_block(task, MAX_TASK_CHARS)
    if not task_text:
        raise ValueError("task must not be empty")

    prompt = f"CURRENT TASK:\n{task_text}"
    if previous_failure.strip():
        failure = _bounded_block(previous_failure, MAX_FAILURE_CHARS)
        prompt += (
            "\n\nPREVIOUS FAILURE EVIDENCE:\n"
            f"{failure}"
        )

    prompt += (
        "\n\nRESULT:\n"
        "Return the existing PASI result markers and one unified git diff between "
        "PASI_RESULT_PATCH_BEGIN and PASI_RESULT_PATCH_END."
    )
    return prompt
