from __future__ import annotations

from typing import Any, Mapping, Sequence

from .contracts import CompletionState, Observation


_KNOWN_OPERATION_STATUSES = frozenset(
    {"queued", "claimed", "generating", "completed", "failed", "cancelled"}
)


def completion_from_operation(
    operation: Mapping[str, Any],
) -> tuple[CompletionState, str, bool]:
    """Map bridge operation evidence to a CUCP completion state.

    A bridge `completed` state is a verified controller acknowledgement that
    generation finished. Response-text availability is reported separately.
    """

    status = operation.get("status")
    if not isinstance(status, str):
        return "unknown", "", False
    status = status.strip().lower()
    text = operation.get("response_text")
    response_text = text if isinstance(text, str) else ""
    response_available = (
        operation.get("response_text_available") is True
        and bool(response_text.strip())
    )

    if status == "failed":
        return "error", response_text, response_available
    if status == "cancelled":
        return "interrupted", response_text, response_available
    if status in {"queued", "claimed", "generating"}:
        return "generating", response_text, response_available
    if status == "completed":
        return "complete", response_text, response_available
    if status not in _KNOWN_OPERATION_STATUSES:
        return "unknown", response_text, response_available
    return "unknown", response_text, response_available


class ChatGPTCompletionDetector:
    """Fail-closed completion detector for normalized bridge/browser evidence."""

    def detect(self, observations: Sequence[Observation]) -> CompletionState:
        if not observations:
            return "unknown"

        latest = observations[-1]
        operation = latest.data.get("operation")
        if isinstance(operation, Mapping):
            state, _, _ = completion_from_operation(operation)
            if state in {"complete", "error", "interrupted", "generating"}:
                return state

        browser = latest.data.get("browser")
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
