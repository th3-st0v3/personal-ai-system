from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class ReplayResult:
    operation_id: str
    first_submission_id: str
    replay_submission_id: str
    duplicate_user_message_delta: int
    idempotent: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            'operation_id': self.operation_id,
            'first_submission_id': self.first_submission_id,
            'replay_submission_id': self.replay_submission_id,
            'duplicate_user_message_delta': self.duplicate_user_message_delta,
            'idempotent': self.idempotent,
        }

def simulate_replay(idempotency_key: str | None = None) -> ReplayResult:
    key = idempotency_key or uuid.uuid4().hex
    operation_id = 'op-' + uuid.uuid4().hex
    seen: dict[str, str] = {}
    user_messages = 0

    def submit() -> str:
        nonlocal user_messages
        existing = seen.get(key)
        if existing is not None:
            return existing
        submission_id = 'submission-' + uuid.uuid4().hex
        seen[key] = submission_id
        user_messages += 1
        return submission_id

    first = submit()
    replay = submit()
    return ReplayResult(operation_id, first, replay, user_messages - 1, first == replay and user_messages == 1)

def main() -> int:
    parser = argparse.ArgumentParser(description='Run the deterministic PASI idempotency replay simulation.')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    result = simulate_replay()
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"PASI replay simulation: {'PASS' if result.idempotent else 'FAIL'}")
        print(f'duplicate_user_message_delta={result.duplicate_user_message_delta}')
    return 0 if result.idempotent else 1

if __name__ == '__main__':
    raise SystemExit(main())