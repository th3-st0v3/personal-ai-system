from __future__ import annotations

from typing import Protocol

from .research_collector_schema import ResearchRequest, ResearchResult


class ResearchCollector(Protocol):
    """Provider-independent boundary for executing a research request."""

    def collect(self, request: ResearchRequest) -> ResearchResult:
        """Collect research evidence for a request."""
        ...
