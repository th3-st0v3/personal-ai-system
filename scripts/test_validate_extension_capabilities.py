from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import validate_extension_capabilities as validator


class ExtensionCapabilityValidationTests(unittest.TestCase):
    def _fixture(self) -> tuple[Path, Path, Path]:
        temp = Path(tempfile.mkdtemp())
        extension = temp / "extension"
        extension.mkdir()
        manifest = {
            "manifest_version": 3,
            "permissions": ["alarms", "storage"],
            "host_permissions": [
                "https://chatgpt.com/*",
                "https://www.chatgpt.com/*",
                "http://127.0.0.1:8765/*",
            ],
            "background": {"service_worker": "background.js"},
            "content_scripts": [{"js": ["background.js", "content.js"]}],
        }
        (extension / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (extension / "background.js").write_text(
            "chrome.alarms.create('x');\n"
            "chrome.storage.local.get('x');\n"
            "chrome.tabs.query({url: ['https://chatgpt.com/*']});\n",
            encoding="utf-8",
        )
        (extension / "content.js").write_text(
            "const bridge = 'http://127.0.0.1:8765';\n"
            "const page = 'https://chatgpt.com/';\n"
            "chrome.runtime.sendMessage({});\n",
            encoding="utf-8",
        )
        py = temp / "bridge.py"
        py.write_text(
            "BRIDGE = 'http://127.0.0.1:8765/browser/health'\n",
            encoding="utf-8",
        )
        return temp, extension, py

    def test_current_repository_manifest_passes(self) -> None:
        self.assertEqual(validator.validate_extension_capabilities(), [])

    def test_templated_fixture_port_does_not_raise(self) -> None:
        temp, extension, _ = self._fixture()
        fixture = temp / "fixture.py"
        fixture.write_text(
            "BROWSER = 'http://127.0.0.1:{port}/json/version'\n",
            encoding="utf-8",
        )
        errors = validator.validate_extension_capabilities(
            manifest_path=extension / "manifest.json",
            extension_root=extension,
            python_files=[fixture],
        )
        self.assertEqual(errors, [])

    def test_missing_permission_is_reported(self) -> None:
        temp, extension, _ = self._fixture()
        manifest_path = extension / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["permissions"].remove("alarms")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        errors = validator.validate_extension_capabilities(
            manifest_path=manifest_path,
            extension_root=extension,
            python_files=[],
        )
        self.assertTrue(
            any("chrome.alarms requires manifest permission" in error for error in errors)
        )
        temp.joinpath("keep").touch()

    def test_missing_host_permission_is_reported(self) -> None:
        temp, extension, _ = self._fixture()
        manifest_path = extension / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["host_permissions"].remove("http://127.0.0.1:8765/*")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        errors = validator.validate_extension_capabilities(
            manifest_path=manifest_path,
            extension_root=extension,
            python_files=[],
        )
        self.assertTrue(
            any("required PASI bridge host permission is missing" in error for error in errors)
        )
        temp.joinpath("keep").touch()

    def test_unknown_chrome_api_requires_contract_entry(self) -> None:
        temp, extension, _ = self._fixture()
        (extension / "content.js").write_text(
            "chrome.unknownApi.execute({});\n",
            encoding="utf-8",
        )

        errors = validator.validate_extension_capabilities(
            manifest_path=extension / "manifest.json",
            extension_root=extension,
            python_files=[],
        )
        self.assertTrue(
            any(
                "chrome.scripting is used but has no declared capability contract"
                in error
                for error in errors
            )
        )
        temp.joinpath("keep").touch()

    def test_python_bridge_url_matches_extension_host_contract(self) -> None:
        temp, extension, py = self._fixture()
        errors = validator.validate_extension_capabilities(
            manifest_path=extension / "manifest.json",
            extension_root=extension,
            python_files=[py],
        )
        self.assertEqual(errors, [])
        temp.joinpath("keep").touch()

    def test_bridge_origin_without_trailing_slash_matches_wildcard_host(self) -> None:
        pattern = validator.LOCAL_BRIDGE_HOST_PATTERN
        self.assertTrue(validator._host_pattern_matches("http://127.0.0.1:8765", pattern))
        self.assertTrue(
            validator._host_pattern_matches(
                "http://127.0.0.1:8765/browser/health",
                pattern,
            )
        )


if __name__ == "__main__":
    unittest.main()
