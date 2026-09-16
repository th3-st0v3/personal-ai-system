"""Provider-independent computer-use control-plane contracts."""

from .chatgpt import ChatGPTAdapter, ChatGPTAdapterError, UrllibBridgeTransport
from .completion import ChatGPTCompletionDetector
from .contracts import (
    ActionKind,
    ActionProposal,
    ActionRisk,
    AIResponse,
    CompletionState,
    ControlEvent,
    ControlPhase,
    ContextPackage,
    Observation,
    Session,
)
from .vscode import Diagnostic, VSCodeEvidenceAdapter, VSCodeEvidenceError

__all__ = [
    "ActionKind",
    "ActionProposal",
    "ActionRisk",
    "AIResponse",
    "CompletionState",
    "ControlEvent",
    "ControlPhase",
    "ContextPackage",
    "Observation",
    "Session",
    "Diagnostic",
    "VSCodeEvidenceAdapter",
    "VSCodeEvidenceError",
    "ChatGPTAdapter",
    "ChatGPTAdapterError",
    "UrllibBridgeTransport",
    "ChatGPTCompletionDetector",
]
