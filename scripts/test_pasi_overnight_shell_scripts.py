from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    ROOT / "scripts" / "start_pasi_overnight.sh",
    ROOT / "scripts" / "stop_pasi_overnight.sh",
    ROOT / "scripts" / "status_pasi_overnight.sh",
)


class TestPasiOvernightShellScripts(unittest.TestCase):
    def test_operator_shell_scripts_pass_bash_syntax(self) -> None:
        for script in SCRIPTS:
            self.assertTrue(script.is_file(), script)
            result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
