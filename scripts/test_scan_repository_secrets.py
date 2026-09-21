from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import scan_repository_secrets as scanner

class SecretScannerTests(unittest.TestCase):
    def test_detects_high_confidence_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'secret.txt').write_text('GROQ=gsk_' + 'A' * 30 + '\\n', encoding='utf-8')
            with mock.patch.object(scanner, 'tracked_files', return_value=[root / 'secret.txt']):
                findings = scanner.scan(root)
        self.assertEqual(findings[0]['type'], 'groq_key')

    def test_ignores_binary_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / 'binary.bin'
            path.write_bytes(b'gsk_' + b'A' * 30 + b'\\x00')
            with mock.patch.object(scanner, 'tracked_files', return_value=[path]):
                findings = scanner.scan(root)
        self.assertEqual(findings, [])

    def test_allows_common_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / 'example.txt'
            path.write_text('API_KEY="YOUR_EXAMPLE_API_KEY_VALUE"', encoding='utf-8')
            with mock.patch.object(scanner, 'tracked_files', return_value=[path]):
                findings = scanner.scan(root)
        self.assertEqual(findings, [])

if __name__ == '__main__':
    unittest.main()
