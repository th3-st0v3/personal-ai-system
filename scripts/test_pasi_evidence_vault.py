from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.pasi_evidence_vault import EvidenceVault

class EvidenceVaultTests(unittest.TestCase):
    def test_wal_vault_persists_and_reads_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'vault.sqlite3'
            vault = EvidenceVault(path)
            evidence_id = vault.append(run_id='run-1', task_id='task-1', event_kind='verification', payload={'result': 'PASS'})
            rows = vault.list_task('run-1', 'task-1')
            self.assertEqual(rows[0]['evidence_id'], evidence_id)
            self.assertEqual(rows[0]['payload']['result'], 'PASS')
            with sqlite3.connect(path) as db:
                mode = db.execute('PRAGMA journal_mode').fetchone()[0]
            self.assertEqual(mode.lower(), 'wal')

if __name__ == '__main__':
    unittest.main()