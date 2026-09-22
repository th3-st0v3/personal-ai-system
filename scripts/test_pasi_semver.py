from __future__ import annotations

import unittest

from scripts.pasi_semver import Version, bump, parse_version

class SemverTests(unittest.TestCase):
    def test_patch_for_fix(self) -> None:
        self.assertEqual(str(bump(Version(1,2,3), ['fix: repair'])), '1.2.4')
    def test_minor_for_feature(self) -> None:
        self.assertEqual(str(bump(Version(1,2,3), ['feat: add'])), '1.3.0')
    def test_major_for_breaking_change(self) -> None:
        self.assertEqual(str(bump(Version(1,2,3), ['feat!: break API'])), '2.0.0')
    def test_parsing_accepts_v_prefix(self) -> None:
        self.assertEqual(parse_version('v2.4.1').patch, 1)

if __name__ == '__main__':
    unittest.main()