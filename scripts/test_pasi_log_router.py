from __future__ import annotations

import subprocess
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
