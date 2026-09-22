from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'install_pasi_self_hosted_runner.sh'

class RunnerInstallTests(unittest.TestCase):
    def test_installer_uses_short_lived_env_token_and_does_not_persist_it(self) -> None:
        source = SCRIPT.read_text(encoding='utf-8')
        self.assertIn('PASI_RUNNER_TOKEN', source)
        self.assertIn('--token "$RUNNER_TOKEN"', source)
        self.assertIn('Registration token was not persisted', source)
        self.assertNotIn('PASI_RUNNER_TOKEN=', source.replace('PASI_RUNNER_TOKEN:',''))

    def test_installer_uses_required_pasi_labels(self) -> None:
        source = SCRIPT.read_text(encoding='utf-8')
        self.assertIn('pasi-desktop,pasi-wsl,pasi-capabilities-v1', source)
        self.assertIn('--unattended', source)
        self.assertIn('--replace', source)

if __name__ == '__main__':
    unittest.main()