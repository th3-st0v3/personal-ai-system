from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestPasi168HourLauncherContract(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (ROOT / "scripts" / "start_pasi_168h.sh").read_text(encoding="utf-8")

    def test_launcher_verifies_native_browser_before_detaching_runner(self) -> None:
        preflight = self.source.index("=== VERIFYING NATIVE CHATGPT BROWSER ===")
        runner = self.source.index("pasi_extended_runtime_entrypoint.py")
        self.assertLess(preflight, runner)
        self.assertIn("http://127.0.0.1:8765/browser/health", self.source)
        self.assertIn('manifest_path = root / "automation" / "chromium" / "pasi-chatgpt" / "manifest.json"', self.source)
        self.assertNotIn("127.0.0.1:8766", self.source)
        self.assertNotIn("pasi_controller_server.py", self.source)
        self.assertIn('actual_version != expected_version.strip()', self.source)
        self.assertIn('if data.get("native_controller") is not True:', self.source)
        self.assertIn("auth_required", self.source)
        self.assertIn("browser_deadline=$((SECONDS + 30))", self.source)
        self.assertIn("exit 8", self.source)

    def test_launcher_does_not_report_started_when_browser_preflight_fails(self) -> None:
        failure = self.source.index("exit 8")
        started = self.source.index("Started PASI extended runner")
        self.assertLess(failure, started)


class TestBranchHygieneWorkflowContract(unittest.TestCase):
    def test_cleanup_run_is_not_cancelled_by_another_cleanup_trigger(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "branch-hygiene.yml").read_text(encoding="utf-8")
        self.assertIn("concurrency:", workflow)
        self.assertIn("cancel-in-progress: false", workflow)


if __name__ == "__main__":
    unittest.main()
