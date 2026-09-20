from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

from automation.computer_use import setup_requirements


class TestPasiSetupRequirements(unittest.TestCase):
    def test_parse_requirements_accepts_bounded_downloads_and_logins(self) -> None:
        response = """PASI_SETUP_REQUIREMENTS_BEGIN
{"downloads":[{"name":"Playwright","version":"1.0.0","source":"https://example.com/tool","reason":"browser test","required":true,"kind":"tool"}],"logins":[{"name":"Example","url":"https://example.com/login","reason":"session needed","required":true,"verification":"login|mfa"}]}
PASI_SETUP_REQUIREMENTS_END"""
        parsed = setup_requirements.parse_requirements(response)
        self.assertEqual(parsed["downloads"][0]["name"], "Playwright")
        self.assertEqual(parsed["logins"][0]["url"], "https://example.com/login")

    def test_parser_rejects_non_https_sources(self) -> None:
        response = """PASI_SETUP_REQUIREMENTS_BEGIN
{"downloads":[{"name":"unsafe","source":"http://example.com/tool","required":true}],"logins":[]}
PASI_SETUP_REQUIREMENTS_END"""
        with self.assertRaises(ValueError):
            setup_requirements.parse_requirements(response)


    def test_main_check_builds_complete_prerequisite_report(self) -> None:
        import scripts.pasi_setup as pasi_setup

        with patch.object(pasi_setup, "_runtime_observation", return_value=None):
            with patch.object(pasi_setup, "_health", return_value={"status": "ok"}):
                with patch.object(pasi_setup.shutil, "which", side_effect=lambda name: "/usr/bin/" + name):
                    with patch.object(sys, "argv", ["pasi_setup.py", "--check"]):
                        self.assertEqual(pasi_setup.main(), 0)

    def test_record_requirements_deduplicates_and_never_writes_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = {"downloads":[{"name":"A","version":"1","source":"https://example.com/a","reason":"first","required":True,"kind":"tool"}],"logins":[]}
            second = {"downloads":[{"name":"A","version":"1","source":"https://example.com/a","reason":"updated","required":True,"kind":"tool"}],"logins":[{"name":"Example","url":"https://example.com/login","reason":"account","required":False,"verification":"mfa"}]}
            setup_requirements.record_requirements(root, first)
            result = setup_requirements.record_requirements(root, second)
            self.assertEqual(result["download_count"], 1)
            self.assertEqual(result["login_count"], 1)
            payload = json.loads((root / setup_requirements.RUNTIME_RELATIVE_PATH).read_text(encoding="utf-8"))
            self.assertNotIn("password", json.dumps(payload).lower())
            self.assertNotIn("cookie", json.dumps(payload).lower())
            self.assertNotIn("token", json.dumps(payload).lower())


if __name__ == "__main__":
    unittest.main()
