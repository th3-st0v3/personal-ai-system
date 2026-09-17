from __future__ import annotations

import unittest
from unittest.mock import patch

from automation.computer_use.research import ResearchAdapterError, ResearchSource
from scripts.pasi_research import search


class TestPasiResearch(unittest.TestCase):
    def test_research_source_requires_https(self) -> None:
        with self.assertRaises(ResearchAdapterError):
            ResearchSource(url="http://example.com", title="Example")

    def test_research_source_has_stable_fingerprint(self) -> None:
        source = ResearchSource(url="https://example.com", title="Example", content="hello")
        self.assertEqual(source.fingerprint, source.fingerprint)
        self.assertEqual(len(source.fingerprint), 64)

    def test_search_requires_api_key_without_network_access(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "PERPLEXITY_API_KEY"):
                search("test")


if __name__ == "__main__":
    unittest.main()
