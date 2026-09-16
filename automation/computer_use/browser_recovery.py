from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .browser_challenge import BrowserChallenge
from .research import HTTPSResearchAdapter, ResearchAdapterError


@dataclass(frozen=True)
class BrowserRecoveryResult:
    """Safe recovery result for a browser challenge.

    A successful recovery comes from an independent, allowed source. It never
    represents a solved challenge or a token/cookie extracted from the challenged
    site.
    """

    status: str
    provider: str
    result_text: str = ""
    source_url: str = ""
    source_title: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"fallback_succeeded", "unavailable"}:
            raise ValueError("unsupported browser recovery status")
        if not self.provider.strip():
            raise ValueError("recovery provider is required")


class BrowserFallbackResolver(Protocol):
    """Resolve a blocked task without attempting to defeat the challenged site."""

    async def resolve(
        self,
        task: str,
        challenge: BrowserChallenge,
    ) -> BrowserRecoveryResult | None: ...


@dataclass(frozen=True)
class ResearchFallbackResolver:
    """Use the existing read-only research layer as an alternate-source fallback.

    The resolver deliberately searches for independent sources instead of
    re-requesting the challenged URL. This keeps scraping resilience useful while
    preserving the site's challenge boundary.
    """

    research: HTTPSResearchAdapter
    max_result_chars: int = 12_000

    def __post_init__(self) -> None:
        if self.max_result_chars <= 0:
            raise ValueError("max_result_chars must be positive")

    async def resolve(
        self,
        task: str,
        challenge: BrowserChallenge,
    ) -> BrowserRecoveryResult | None:
        del challenge
        try:
            observation = self.research.search(task)
        except ResearchAdapterError:
            return None

        sources = observation.data.get("sources", [])
        if not isinstance(sources, list):
            return None

        candidates = [source for source in sources if isinstance(source, dict)]
        for source in candidates:
            url = source.get("url")
            title = source.get("title")
            content = source.get("content") or source.get("snippet")
            if not isinstance(url, str) or not isinstance(title, str):
                continue
            if not isinstance(content, str) or not content.strip():
                continue
            return BrowserRecoveryResult(
                status="fallback_succeeded",
                provider="research",
                result_text=content[: self.max_result_chars],
                source_url=url,
                source_title=title,
            )

        return None
