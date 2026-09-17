from __future__ import annotations

import json
import unittest
from typing import Any, Sequence
from unittest.mock import patch

from automation.computer_use.research import (
    HTTPSResearchAdapter,
    ResearchAdapterError,
    ResearchSource,
)


class FakeSearchProvider:
    def __init__(self, sources: Sequence[ResearchSource]) -> None:
        self.sources = tuple(sources)
        self.limits: list[int] = []

    def search(self, query: str, *, limit: int) -> Sequence[ResearchSource]:
        self.limits.append(limit)
        return self.sources


class ResearchSourceTests(unittest.TestCase):
    def test_https_source_requires_title_and_valid_quality(self) -> None:
        with self.assertRaises(ResearchAdapterError):
            ResearchSource("http://example.com", "Example")
        with self.assertRaises(ResearchAdapterError):
            ResearchSource("https://example.com", "", source_quality=50)
        with self.assertRaises(ResearchAdapterError):
            ResearchSource("https://example.com", "Example", source_quality=101)

    def test_fingerprint_excludes_retrieval_timestamp(self) -> None:
        first = ResearchSource("https://example.com", "Example", content="same", retrieved_at="2026-01-01T00:00:00+00:00")
        second = ResearchSource("https://example.com", "Example", content="same", retrieved_at="2026-01-02T00:00:00+00:00")
        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_ranking_is_deterministic(self) -> None:
        sources = [
            ResearchSource("https://b.example", "B", source_quality=20),
            ResearchSource("https://a.example", "A", source_quality=20),
            ResearchSource("https://c.example", "C", source_quality=80),
        ]
        ranked = HTTPSResearchAdapter.rank_sources(sources)
        self.assertEqual([item.url for item in ranked], ["https://c.example", "https://a.example", "https://b.example"])


class ResearchAdapterTests(unittest.TestCase):
    def test_search_is_bounded_and_sorted_by_explicit_metadata(self) -> None:
        provider = FakeSearchProvider(
            [
                ResearchSource("https://b.example", "B", source_quality=10),
                ResearchSource("https://a.example", "A", source_quality=90),
            ]
        )
        observation = HTTPSResearchAdapter(provider, max_search_results=1).search("pasi")
        self.assertEqual(provider.limits, [1])
        self.assertEqual(observation.data["sources"][0]["url"], "https://a.example")
        self.assertEqual(observation.data["sources"][0]["source_quality"], 90)

    def test_search_requires_provider_and_bounded_query(self) -> None:
        with self.assertRaises(ResearchAdapterError):
            HTTPSResearchAdapter().search("test")
        provider = FakeSearchProvider([])
        adapter = HTTPSResearchAdapter(provider)
        with self.assertRaises(ResearchAdapterError):
            adapter.search("x" * 501)

    def test_read_rejects_non_https_and_private_targets(self) -> None:
        adapter = HTTPSResearchAdapter()
        for url in (
            "http://example.com",
            "file:///tmp/a",
            "ftp://example.com/a",
            "https://127.0.0.1/",
            "https://10.0.0.1/",
            "https://169.254.169.254/",
            "https://localhost/",
        ):
            with self.assertRaises(ResearchAdapterError):
                adapter.read(url)

    def test_read_rejects_unsupported_content_type(self) -> None:
        class Headers:
            def get_content_type(self) -> str:
                return "application/octet-stream"

        class Response:
            headers = Headers()

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self, size: int) -> bytes:
                return b"data"

        adapter = HTTPSResearchAdapter()
        with patch("automation.computer_use.research.socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 443))]):
            with patch("automation.computer_use.research.build_opener") as opener:
                opener.return_value.open.return_value = Response()
                with self.assertRaises(ResearchAdapterError):
                    adapter.read("https://example.com/file")

    def test_read_marks_content_as_untrusted_and_is_bounded(self) -> None:
        class Headers:
            def get_content_type(self) -> str:
                return "text/plain"

        class Response:
            headers = Headers()

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self, size: int) -> bytes:
                self.size = size
                return b"hello"

        response = Response()
        adapter = HTTPSResearchAdapter(max_content_chars=3)
        with patch("automation.computer_use.research.socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 443))]):
            with patch("automation.computer_use.research.build_opener") as opener:
                opener.return_value.open.return_value = response
                observation = adapter.read("https://example.com/file")
        self.assertEqual(observation.data["content"], "hel\n[content truncated]")
        self.assertTrue(observation.data["untrusted"])
        self.assertEqual(observation.data["content_type"], "text/plain")
        self.assertEqual(observation.data["fingerprint"], __import__("hashlib").sha256(observation.data["content"].encode()).hexdigest())

    def test_source_serialization_is_json_safe(self) -> None:
        source = ResearchSource("https://example.com", "Example", snippet="text", content="body")
        self.assertIsInstance(json.dumps(source.to_dict()), str)


if __name__ == "__main__":
    unittest.main()
