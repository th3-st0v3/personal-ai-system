from __future__ import annotations

import unittest

from scripts.pasi_idempotency_replay import simulate_replay

class IdempotencyReplayTests(unittest.TestCase):
    def test_replay_does_not_duplicate_submission(self) -> None:
        result = simulate_replay('stable-operation-key')
        self.assertTrue(result.idempotent)
        self.assertEqual(result.first_submission_id, result.replay_submission_id)
        self.assertEqual(result.duplicate_user_message_delta, 0)

if __name__ == '__main__':
    unittest.main()