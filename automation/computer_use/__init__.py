"""Provider-independent computer-use control-plane contracts."""

from .browser_challenge import (
    BrowserChallenge,
    ChallengeKind,
    ChallengeState,
    detect_browser_challenge,
    mark_cleared,
    mark_waiting_human,
)
from .browser_recovery import (
    BrowserFallbackResolver,
    BrowserRecoveryResult,
    ResearchFallbackResolver,
)
from .browser_use_adapter import (
    BrowserRunResult,
    BrowserUseAdapterError,
    BrowserUseTaskAdapter,
    BrowserUseUnavailable,
)
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
from .github import (
    GitHubAdapterError,
    GitHubControlAdapter,
    GitHubTransport,
    UrllibGitHubTransport,
)
from .research import (
    DuckDuckGoHTMLSearchProvider,
    HTTPSResearchAdapter,
    ResearchAdapterError,
    ResearchSource,
)
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
    "DuckDuckGoHTMLSearchProvider",
    "ResearchAdapterError",
    "ResearchSource",
    "IndependentReviewer",
    "ReviewError",
    "ReviewRequest",
    "ReviewResult",
    "ReviewTransport",
    "TransportBackedReviewer",
    "BrowserChallenge",
    "ChallengeKind",
    "ChallengeState",
    "detect_browser_challenge",
    "mark_cleared",
    "mark_waiting_human",
    "BrowserRunResult",
    "BrowserUseAdapterError",
    "BrowserUseTaskAdapter",
    "BrowserUseUnavailable",
    "GitHubAdapterError",
    "GitHubControlAdapter",
    "GitHubTransport",
    "UrllibGitHubTransport",
    "BrowserFallbackResolver",
    "BrowserRecoveryResult",
    "ResearchFallbackResolver",
]
