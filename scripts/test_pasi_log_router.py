from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "scripts" / "pasi_log_router.py"


class TestPasiLogRouter(unittest.TestCase):
    def test_rotates_and_bounds_log_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "service.log"
            command = [
                sys.executable,
                "-c",
                "import sys; [print('x' * 120) for _ in range(100)]",
            ]
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROUTER),
                    "--log",
                    str(log),
                    "--max-bytes",
                    "512",
                    "--backups",
                    "2",
                    "--",
                    *command,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            files = sorted(log.parent.glob("service.log*"))
            self.assertEqual({path.name for path in files}, {
                "service.log",
                "service.log.1",
                "service.log.2",
            })
            self.assertTrue(all(path.stat().st_size <= 512 for path in files))
            self.assertGreater(sum(path.stat().st_size for path in files), 0)

    def test_child_exit_status_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROUTER),
                    "--log",
                    str(Path(directory) / "service.log"),
                    "--",
                    sys.executable,
                    "-c",
                    "raise SystemExit(7)",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 7)

    @unittest.skipUnless(os.name == "posix", "POSIX process groups are required")
    def test_sigterm_terminates_managed_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "service.log"
            grandchild_pid_file = root / "grandchild.pid"
            grandchild_ready = root / "grandchild.ready"
            terminated_marker = root / "grandchild.terminated"

            grandchild_code = """
import pathlib
import signal
import sys
import time

marker = pathlib.Path(sys.argv[1])
ready = pathlib.Path(sys.argv[2])

def handle_term(_signum, _frame):
    marker.write_text("terminated", encoding="utf-8")
    raise SystemExit(0)

signal.signal(signal.SIGTERM, handle_term)
signal.signal(signal.SIGINT, handle_term)
ready.write_text("ready", encoding="utf-8")
while True:
    time.sleep(60)
""".strip()
            child_code = """
import pathlib
import signal
import subprocess
import sys
import time

pid_file = pathlib.Path(sys.argv[1])
marker = sys.argv[2]
ready = pathlib.Path(sys.argv[3])
grandchild = subprocess.Popen(
    [
        sys.executable,
        "-c",
        sys.argv[4],
        marker,
        str(ready),
    ],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
deadline = time.monotonic() + 5.0
while time.monotonic() < deadline and not ready.exists():
    time.sleep(0.01)
if not ready.exists():
    raise SystemExit("grandchild did not become signal-ready")
pid_file.write_text(str(grandchild.pid), encoding="utf-8")
signal.pause()
""".strip()

            router = subprocess.Popen(
                [
                    sys.executable,
                    str(ROUTER),
                    "--log",
                    str(log),
                    "--",
                    sys.executable,
                    "-c",
                    child_code,
                    str(grandchild_pid_file),
                    str(terminated_marker),
                    str(grandchild_ready),
                    grandchild_code,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            try:
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline and not grandchild_pid_file.exists():
                    time.sleep(0.05)
                self.assertTrue(
                    grandchild_pid_file.exists(),
                    "managed child did not publish its signal-ready descendant PID",
                )

                os.kill(router.pid, signal.SIGTERM)
                self.assertEqual(router.wait(timeout=5.0), 128 + signal.SIGTERM)

                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline and not terminated_marker.exists():
                    time.sleep(0.05)
                self.assertTrue(
                    terminated_marker.exists(),
                    "SIGTERM did not reach the managed descendant process group",
                )
            finally:
                if router.poll() is None:
                    router.terminate()
                    try:
                        router.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        router.kill()
                        router.wait(timeout=2.0)


if __name__ == "__main__":
    unittest.main()
