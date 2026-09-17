import base64
import unittest
from unittest.mock import patch

import github_ingestion


class TestGitHubIngestion(unittest.TestCase):
    def test_parse_rejects_credentials_and_nonstandard_ports(self):
        for url in (
            "https://user:pass@api.github.com/repos/o/r/contents/a.txt",
            "https://api.github.com:444/repos/o/r/contents/a.txt",
            "http://api.github.com/repos/o/r/contents/a.txt",
        ):
            with self.assertRaises(ValueError):
                github_ingestion._parse(url)

    def test_fetch_requires_valid_base64(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, size):
                return b'{"type":"file","content":"%%%not-base64%%%"}'

        with patch("github_ingestion.urllib.request.urlopen", return_value=Response()):
            with self.assertRaises(ValueError, msg="invalid base64 should be rejected"):
                github_ingestion.fetch_public_file("https://api.github.com/repos/o/r/contents/a.txt")

    def test_fetch_accepts_wrapped_base64(self):
        encoded = base64.b64encode(b"hello").decode()
        wrapped = encoded[:2] + "\n" + encoded[2:]

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, size):
                return ('{"type":"file","content":"' + wrapped + '","sha":"abc"}').encode()

        with patch("github_ingestion.urllib.request.urlopen", return_value=Response()):
            result = github_ingestion.fetch_public_file("https://api.github.com/repos/o/r/contents/a.txt")
        self.assertEqual(result["content"], "hello")
        self.assertEqual(result["version"], "abc")


if __name__ == "__main__":
    unittest.main()
