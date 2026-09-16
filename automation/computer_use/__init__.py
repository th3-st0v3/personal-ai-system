"""Provider-independent computer-use control-plane contracts."""

from .chatgpt import ChatGPTAdapter, ChatGPTAdapterError, UrllibBridgeTransport
from .completion import ChatGPTCompletionDetector
from .context import (
    ConditionalPromptEngine,
    ContextEngineError,
    EvidenceContextCollector,
    FollowUpDecision,
    TaskState,
)
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
from .research import HTTPSResearchAdapter, ResearchAdapterError, ResearchSource
from .review import (
    IndependentReviewer,
    ReviewError,
    ReviewRequest,
    ReviewResult,
    ReviewTransport,
    TransportBackedReviewer,
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
    "ConditionalPromptEngine",
    "ContextEngineError",
    "EvidenceContextCollector",
    "FollowUpDecision",
    "TaskState",
    "HTTPSResearchAdapter",
    "ResearchAdapterError",
    "ResearchSource",
    "IndependentReviewer",
    "ReviewError",
    "ReviewRequest",
    "ReviewResult",
    "ReviewTransport",
    "TransportBackedReviewer",
]
