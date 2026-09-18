from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts import pasi_pull_shark_status as status


class TestPasiPullSharkStatus(unittest.TestCase):
    def test_calculate_status_reports_next_target_and_remaining(self) -> None:
        result = status.calculate_status("th3-st0v3/personal-ai-system", "th3-st0v3", 84)
        self.assertEqual(result.next_target, 128)
        self.assertEqual(result.remaining_to_next_target, 44)
        self.assertEqual(result.tier_reached, "16 merged PRs")

    def test_calculate_status_reaches_gold_target(self) -> None:
        result = status.calculate_status("repo", "author", 1024)
        self.assertIsNone(result.next_target)
        self.assertEqual(result.remaining_to_next_target, 0)
        self.assertEqual(result.tier_reached, "1024 merged PRs")

    def test_collect_status_uses_authenticated_login_by_default(self) -> None:
        with patch.object(status.shutil, "which", return_value="/usr/bin/gh"):
            with patch.object(status, "_login", return_value="th3-st0v3"):
                with patch.object(status, "_merged_count", return_value=84) as count:
                    result = status.collect_status("th3-st0v3/personal-ai-system")
        count.assert_called_once_with("th3-st0v3/personal-ai-system", "th3-st0v3")
        self.assertEqual(result.merged_prs_observed, 84)
        self.assertEqual(result.author, "th3-st0v3")


if __name__ == "__main__":
    unittest.main()
