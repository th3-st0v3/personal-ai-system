"""P1-B: stage-event vocabulary + helpers for the M2 baseline.

Uses the EXISTING events.jsonl stream: pass in the runner's own ``log_event(kind, **data)`` (which already stamps an
ISO ``timestamp``). Nothing here writes files or invents a parallel telemetry system.

Vocabulary (all events also carry ``timestamp`` from log_event; browser marks are epoch milliseconds):

  prompt_dispatch_started  task_id attempt [batch_id batch_size mode]
  prompt_queued            task_id attempt operation_id
  browser_timing           operation_id injected_at_ms ack_at_ms generation_start_ms completed_at_ms
                           user_messages_added (must be 1) ack_verified submission_via
  response_received        task_id attempt operation_id chars
  gate_started             tier(0|1) task_id attempt
  gate_finished            tier task_id attempt result(pass|fail|not_evaluated) duration_ms classification
  failure_classified       task_id attempt classification(code|infra|not_evaluated|preexisting) stage
  recovery_started         operation_id reason
  recovery_finished        operation_id reason duration_ms outcome
  task_attempt_started / task_completed / task_failed   (already emitted by pasi_overnight_engine_v2)
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable

Emit = Callable[..., None]

CLASSIFICATIONS = ("code", "infra", "not_evaluated", "preexisting")

# Conservative on purpose: anything not clearly a code failure is NOT blamed on the patch.
_INFRA_MARKERS = re.compile(
    r"(timed out|timeout|command not found|no space left|could not resolve|connection (?:refused|reset)|"
    r"temporary failure in name resolution|npm err!|npx:|econnreset|etimedout|"
    r"browser controller is not reporting|CHAT_(?:AUTH_REQUIRED|USAGE_LIMITED|GUARD_TIMEOUT)|"
    r"PASI_NATIVE:|bridge (?:request|completion) failed|MemoryError|killed)",
    re.IGNORECASE,
)
_CODE_MARKERS = re.compile(
    r"(^FAILED |\bAssertionError\b|\bE\s+assert\b|\d+ failed\b|error: \S+.*\(reportGeneral|\berror TS\d+|"
    r"\bSyntaxError\b|git apply.*(?:patch does not apply|error:)|canonical validation failed)",
    re.IGNORECASE | re.MULTILINE,
)


def classify_failure(stage: str, exit_code: int, output: str) -> str:
    """Return 'code' | 'infra' | 'not_evaluated'. Infra markers win; unknown failures are not_evaluated."""
    if exit_code == 0:
        return "not_evaluated"  # caller should not classify successes; fail closed
    text = output or ""
    if _INFRA_MARKERS.search(text) and not _CODE_MARKERS.search(text):
        return "infra"
    if _CODE_MARKERS.search(text) and not _INFRA_MARKERS.search(text):
        return "code"
    if _CODE_MARKERS.search(text) and _INFRA_MARKERS.search(text):
        return "not_evaluated"  # ambiguous: never tell the model to edit code on ambiguous evidence
    return "not_evaluated"


class StageTimer:
    """Context manager emitting <stage>_started / <stage>_finished with a monotonic duration_ms.

    with StageTimer(log_event, "gate", tier=0, task_id=t, attempt=a) as st:
        ...
        st.result = "pass"; st.classification = "none"
    """

    def __init__(self, emit: Emit, stage: str, **fields: Any) -> None:
        self._emit, self._stage, self._fields = emit, stage, fields
        self.result = "pass"
        self.classification = "none"
        self._t0 = 0.0

    def __enter__(self) -> "StageTimer":
        self._t0 = time.monotonic()
        self._emit(f"{self._stage}_started", **self._fields)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None and self.result == "pass":
            self.result = "not_evaluated"
            self.classification = "infra"
        self._emit(
            f"{self._stage}_finished",
            duration_ms=int((time.monotonic() - self._t0) * 1000),
            result=self.result,
            classification=self.classification,
            **self._fields,
        )
        return False  # never swallow exceptions