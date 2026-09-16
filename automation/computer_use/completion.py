from __future__ import annotations

from typing import Any, Mapping

from .contracts import CompletionState


_KNOWN_OPERATION_STATUSES = frozenset(
    {"queued", "claimed", "generating", "completed", "failed", "cancelled"}
)


def completion_from_operation(
    operation: Mapping[str, Any],
) -> tuple[CompletionState, str]:
    """Map bridge operation evidence to a CUCP completion state.

    A bridge `completed` state is only treated as CUCP `complete` when the
    controller explicitly reports that response text was observed. This keeps
    transport acknowledgement separate from actual response evidence.
    """

    status = operation.get("status")
    if not isinstance(status, str):
        return "unknown", ""
    status = status.strip().lower()
    text = operation.get("response_text")
    response_text = text if isinstance(text, str) else ""

    if status == "failed":
        return "error", response_text
    if status == "cancelled":
        return "interrupted", response_text
    if status in {"queued", "claimed", "generating"}:
        return "generating", response_text
    if status == "completed":
        if operation.get("response_text_available") is True and response_text.strip():
            return "complete", response_text
        return "unknown", response_text
    if status not in _KNOWN_OPERATION_STATUSES:
        return "unknown", response_text
    return "unknown", response_text


class ChatGPTCompletionDetector:
    """Fail-closed completion detector for normalized bridge/browser evidence."""

    def detect(self, observations: list[Mapping[str, Any]]) -> CompletionState:
        if not observations:
            return "unknown"

        latest = observations[-1]
        operation = latest.get("operation")
        if isinstance(operation, Mapping):
            state, _ = completion_from_operation(operation)
            if state != "unknown":
                return state

        browser = latest.get("browser")
        if isinstance(browser, Mapping):
            if browser.get("generation_error"):
                return "error"
            if browser.get("interrupted") is True:
                return "interrupted"
            if browser.get("generation_active") is True:
                return "generating"
            if browser.get("quiet") is True:
                return "quiet"

        return "unknown"
