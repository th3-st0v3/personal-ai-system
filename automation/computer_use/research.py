from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from .contracts import Observation


class ResearchAdapterError(RuntimeError):
    """Raised when a research operation violates the evidence boundary."""


@dataclass(frozen=True)
class ResearchSource:
    """Normalized read-only web source evidence."""

    url: str
    title: str
    snippet: str = ""
    content: str = ""
    retrieved_at: str = ""
    source_quality: int = 0

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ResearchAdapterError("research sources must use an HTTPS URL")
        if not self.title.strip():
            raise ResearchAdapterError("research source title is required")
        if not 0 <= self.source_quality <= 100:
            raise ResearchAdapterError("source_quality must be between 0 and 100")
        if self.retrieved_at:
            try:
                datetime.fromisoformat(self.retrieved_at)
            except ValueError as exc:
                raise ResearchAdapterError("retrieved_at must be ISO-8601") from exc

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "url": self.url,
                "title": self.title,
                "snippet": self.snippet,
                "content": self.content,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "content": self.content,
            "retrieved_at": self.retrieved_at,
            "source_quality": self.source_quality,
            "fingerprint": self.fingerprint,
        }


class SearchProvider(Protocol):
    """Replaceable provider boundary for external search."""

    def search(self, query: str, *, limit: int) -> Sequence[ResearchSource]: ...


class _HTTPSRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str):
        parsed = urlparse(newurl)
        if parsed.scheme != "https":
            raise ResearchAdapterError("redirect target must remain HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass(frozen=True)
class HTTPSResearchAdapter:
    """Bounded HTTPS retrieval/search facade for untrusted web evidence."""

    search_provider: SearchProvider | None = None
    timeout_seconds: float = 15.0
    max_response_bytes: int = 2_000_000
    max_search_results: int = 10
    max_content_chars: int = 100_000

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ResearchAdapterError("timeout_seconds must be positive")
        if self.max_response_bytes <= 0 or self.max_content_chars <= 0 or self.max_search_results <= 0:
            raise ResearchAdapterError("research bounds must be positive")

    def search(self, query: str) -> Observation:
        if not query.strip():
            raise ResearchAdapterError("research query is required")
        if len(query) > 500:
            raise ResearchAdapterError("research query exceeds configured bound")
        if self.search_provider is None:
            raise ResearchAdapterError("no search provider is configured")
        sources = list(self.search_provider.search(query, limit=self.max_search_results))
        normalized = sorted(
            (source.to_dict() for source in sources),
            key=lambda item: (-int(item["source_quality"]), str(item["url"])),
        )[: self.max_search_results]
        return Observation(
            observation_id=f"research-search:{sha256(query.encode('utf-8')).hexdigest()[:16]}",
            session_id="unspecified",
            source="web",
            kind="search",
            data={
                "query": query,
                "sources": normalized,
                "fingerprint": self._fingerprint(normalized),
            },
        )

    def read(self, source: str) -> Observation:
        parsed = urlparse(source)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ResearchAdapterError("research retrieval requires an HTTPS URL")
        request = Request(
            source,
            headers={"Accept": "text/html, text/plain, application/json"},
            method="GET",
        )
        opener = build_opener(_HTTPSRedirectHandler)
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                content_type = response.headers.get_content_type().lower()
                if content_type not in {"text/html", "text/plain", "application/json"}:
                    raise ResearchAdapterError(
                        f"unsupported research content type: {content_type}"
                    )
                raw = response.read(self.max_response_bytes + 1)
        except HTTPError as exc:
            raise ResearchAdapterError(f"research HTTP {exc.code}") from exc
        except URLError as exc:
            raise ResearchAdapterError(f"research request failed: {exc.reason}") from exc

        if len(raw) > self.max_response_bytes:
            raise ResearchAdapterError("research response exceeded configured byte limit")
        text = raw.decode("utf-8", errors="replace")
        if len(text) > self.max_content_chars:
            text = text[: self.max_content_chars] + "\n[content truncated]"
        observed_at = datetime.now(timezone.utc).isoformat()
        return Observation(
            observation_id=f"research-read:{sha256(source.encode('utf-8')).hexdigest()[:16]}",
            session_id="unspecified",
            source="web",
            kind="document",
            data={
                "url": source,
                "content_type": content_type,
                "retrieved_at": observed_at,
                "content": text,
                "fingerprint": sha256(text.encode("utf-8")).hexdigest(),
                "untrusted": True,
            },
        )

    @staticmethod
    def rank_sources(sources: Sequence[ResearchSource]) -> tuple[ResearchSource, ...]:
        return tuple(sorted(sources, key=lambda item: (-item.source_quality, item.url)))

    @staticmethod
    def _fingerprint(value: Any) -> str:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(encoded.encode("utf-8")).hexdigest()
