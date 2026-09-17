from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from automation.computer_use.preapproval import AcquisitionEngine, PreapprovalPolicy


class PreapprovalTests(unittest.TestCase):
    def _policy(self, root: Path, approvals: list[dict[str, object]]) -> PreapprovalPolicy:
        path = root / "policy.json"
        path.write_text(json.dumps({"schema_version": 1, "approvals": approvals}), encoding="utf-8")
        return PreapprovalPolicy(root, path)

    def test_unapproved_download_is_blocked_and_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = AcquisitionEngine(root, policy=self._policy(root, []))
            result = engine.acquire_public_download("https://example.com/tool.tar.gz", task_id="task-1")
            self.assertEqual(result["status"], "blocked")
            self.assertTrue(result["approval_required"])
            self.assertTrue((root / ".runtime" / "automation" / "action-list.md").exists())

    def test_matching_host_download_preapproval_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = self._policy(root, [{"id": "download-example", "action": "public_download", "hosts": ["example.com"], "max_bytes": 1000}])
            decision = policy.approve_public_download("https://example.com/tool.tar.gz", max_bytes=900)
            self.assertTrue(decision.allowed)
            self.assertEqual(decision.approval_id, "download-example")
            self.assertFalse(policy.approve_public_download("http://example.com/tool.tar.gz", max_bytes=900).allowed)
            self.assertFalse(policy.approve_public_download("https://other.example/tool.tar.gz", max_bytes=900).allowed)
            self.assertFalse(policy.approve_public_download("https://example.com/tool.tar.gz", max_bytes=1001).allowed)

    def test_package_install_requires_exact_pin_and_matching_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = self._policy(root, [{"id": "pkg-1", "action": "package_install", "manager": "pip", "packages": ["requests==2.33.0"]}])
            self.assertFalse(policy.approve_package_install("requests").allowed)
            self.assertFalse(policy.approve_package_install("requests>=2.33.0").allowed)
            self.assertTrue(policy.approve_package_install("requests==2.33.0").allowed)
            self.assertFalse(policy.approve_package_install("urllib3==2.8.0").allowed)

    def test_expired_preapproval_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = self._policy(root, [{"id": "expired", "action": "public_download", "hosts": ["example.com"], "max_bytes": 1000, "expires_at": "2020-01-01T00:00:00Z"}])
            self.assertFalse(policy.approve_public_download("https://example.com/tool.tar.gz", max_bytes=100).allowed)


if __name__ == "__main__":
    unittest.main()
