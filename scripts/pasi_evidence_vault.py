from __future__ import annotations

import argparse
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

DEFAULT_PATH = Path.home() / '.pasi' / 'evidence' / 'vault.sqlite3'

class EvidenceVault:
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA synchronous=NORMAL')
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS evidence (evidence_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, task_id TEXT NOT NULL, event_kind TEXT NOT NULL, payload_json TEXT NOT NULL, created_at REAL NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS idx_evidence_run_task ON evidence(run_id, task_id, created_at)')

    def append(self, *, run_id: str, task_id: str, event_kind: str, payload: Mapping[str, Any]) -> str:
        evidence_id = 'evidence-' + uuid.uuid4().hex
        with self._connect() as db:
            db.execute('INSERT INTO evidence(evidence_id, run_id, task_id, event_kind, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)', (evidence_id, run_id, task_id, event_kind, json.dumps(dict(payload), ensure_ascii=False, sort_keys=True), time.time()))
        return evidence_id

    def list_task(self, run_id: str, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute('SELECT evidence_id, event_kind, payload_json, created_at FROM evidence WHERE run_id = ? AND task_id = ? ORDER BY created_at', (run_id, task_id)).fetchall()
        return [{'evidence_id': row[0], 'event_kind': row[1], 'payload': json.loads(row[2]), 'created_at': row[3]} for row in rows]

def main() -> int:
    parser = argparse.ArgumentParser(description='Append/query PASI durable SQLite evidence.')
    parser.add_argument('--path', type=Path, default=DEFAULT_PATH)
    parser.add_argument('--run-id')
    parser.add_argument('--task-id')
    parser.add_argument('--event-kind')
    parser.add_argument('--payload', default='{}')
    parser.add_argument('--list-task', action='store_true')
    args = parser.parse_args()
    vault = EvidenceVault(args.path)
    if args.list_task:
        if not args.run_id or not args.task_id:
            parser.error('--list-task requires --run-id and --task-id')
        print(json.dumps(vault.list_task(args.run_id, args.task_id), indent=2))
        return 0
    if not args.run_id or not args.task_id or not args.event_kind:
        parser.error('--run-id, --task-id, and --event-kind are required')
    evidence_id = vault.append(run_id=args.run_id, task_id=args.task_id, event_kind=args.event_kind, payload=json.loads(args.payload))
    print(evidence_id)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())