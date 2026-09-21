#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_RUNTIME = Path.home() / '.pasi' / 'overnight'

def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}

def recovery_events(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding='utf-8').splitlines()[-200:]
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and any(token in str(value.get('kind', '')).casefold() for token in ('recovery', 'retry', 'pause', 'standby', 'control')):
            events.append(value)
    return events[-12:]

def build_story(runtime: Path) -> dict:
    state = read_json(runtime / 'state.json')
    handoff = read_json(runtime / 'handoff.json')
    source = handoff or state
    return {
        'run_id': source.get('run_id', ''),
        'phase': source.get('phase', 'unknown'),
        'current_task': source.get('current_task', ''),
        'completed_tasks': source.get('completed_tasks', 0),
        'failed_tasks': source.get('failed_tasks', 0),
        'current_attempt': source.get('current_attempt', 0),
        'provider': source.get('last_provider', ''),
        'deadline_at': source.get('deadline_at', ''),
        'stop_reason': source.get('stop_reason', ''),
        'recent_tasks': source.get('recent_tasks', [])[-8:] if isinstance(source.get('recent_tasks', []), list) else [],
        'recovery_events': recovery_events(runtime / 'events.jsonl'),
    }

def main() -> int:
    parser = argparse.ArgumentParser(description='Render a deterministic PASI run story from durable evidence.')
    parser.add_argument('--runtime', type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    story = build_story(args.runtime.expanduser().resolve())
    if args.json:
        print(json.dumps(story, indent=2, ensure_ascii=False))
    else:
        print(f"PASI run {story['run_id'] or '<unknown>'}: {story['phase']} phase")
        print(f"Current task: {story['current_task'] or '<none>'}")
        print(f"Progress: completed={story['completed_tasks']} failed={story['failed_tasks']} attempt={story['current_attempt']}")
        print(f"Provider: {story['provider'] or '<unknown>'}")
        print(f"Deadline: {story['deadline_at'] or '<unknown>'}")
        if story['stop_reason']: print(f"Stop reason: {story['stop_reason']}")
        for event in story['recovery_events'][-5:]: print(f"Event: {event.get('kind', 'unknown')} @ {event.get('timestamp', '?')}")
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
