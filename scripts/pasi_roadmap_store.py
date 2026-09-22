from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

DEFAULT_PATH = Path.home() / '.pasi' / 'roadmaps' / 'catalog.json'
MAX_ROADMAPS = 128
MAX_NAME_CHARS = 160
MAX_RAW_CHARS = 500_000
MAX_TASKS = 512

class RoadmapError(ValueError):
    pass

class RoadmapStore:
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {'schema_version': 1, 'active_roadmap_id': None, 'roadmaps': {}}
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise RoadmapError('roadmap catalog is unreadable') from exc
        if not isinstance(raw, dict) or not isinstance(raw.get('roadmaps', {}), dict):
            raise RoadmapError('roadmap catalog is invalid')
        if raw.get('schema_version') != 1:
            raise RoadmapError('unsupported roadmap catalog schema')
        return raw

    def _write(self, payload: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.json.tmp')
        temp.write_text(json.dumps(dict(payload), indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        temp.replace(self.path)

    @staticmethod
    def _clone(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False))

    @staticmethod
    def _summary(roadmap: Mapping[str, Any]) -> dict[str, Any]:
        raw = str(roadmap.get('raw_text', ''))
        return {
            'id': roadmap['id'],
            'name': roadmap['name'],
            'created_at': roadmap['created_at'],
            'updated_at': roadmap['updated_at'],
            'archived': bool(roadmap.get('archived', False)),
            'task_count': len(roadmap.get('tasks', [])),
            'raw_chars': len(raw),
            'source_ids': list(roadmap.get('source_ids', [])),
        }

    def list(self, *, include_archived: bool = False) -> dict[str, Any]:
        with self._lock:
            payload = self._read()
            active = payload.get('active_roadmap_id')
            if active not in payload['roadmaps'] or payload['roadmaps'][active].get('archived', False):
                active = None
            items = [
                self._summary(item)
                for item in payload['roadmaps'].values()
                if include_archived or not item.get('archived', False)
            ]
            items.sort(key=lambda item: (item['archived'], -float(item['updated_at'])))
            return {'active_roadmap_id': active, 'roadmaps': items}


    def active(self) -> dict[str, Any] | None:
        with self._lock:
            payload = self._read()
            roadmap_id = payload.get('active_roadmap_id')
            if not isinstance(roadmap_id, str):
                return None
            item = payload['roadmaps'].get(roadmap_id)
            if not item or item.get('archived', False):
                return None
            return self._clone(item)

    def get(self, roadmap_id: str, *, include_archived: bool = False) -> dict[str, Any]:
        with self._lock:
            item = self._read()['roadmaps'].get(str(roadmap_id))
            if not item or (item.get('archived', False) and not include_archived):
                raise RoadmapError('roadmap not found')
            return self._clone(item)

    def create(self, name: str, *, raw_text: str = '', tasks: Sequence[Mapping[str, Any]] = (), source_ids: Sequence[str] = ()) -> dict[str, Any]:
        clean_name = ' '.join(str(name).split()).strip()
        if not clean_name or len(clean_name) > MAX_NAME_CHARS:
            raise RoadmapError('roadmap name is required and bounded')
        if len(raw_text) > MAX_RAW_CHARS:
            raise RoadmapError('roadmap text exceeds the configured limit')
        task_list = [self._clone(item) for item in tasks if isinstance(item, Mapping)]
        if len(task_list) > MAX_TASKS:
            raise RoadmapError('roadmap task count exceeds the configured limit')
        with self._lock:
            payload = self._read()
            if len(payload['roadmaps']) >= MAX_ROADMAPS:
                raise RoadmapError('roadmap catalog is full')
            now = time.time()
            roadmap_id = 'rm-' + uuid.uuid4().hex
            payload['roadmaps'][roadmap_id] = {
                'id': roadmap_id,
                'name': clean_name,
                'created_at': now,
                'updated_at': now,
                'archived': False,
                'raw_text': raw_text,
                'tasks': task_list,
                'source_ids': list(dict.fromkeys(str(value) for value in source_ids if str(value).strip())),
            }
            payload['active_roadmap_id'] = roadmap_id
            self._write(payload)
            return self._clone(payload['roadmaps'][roadmap_id])

    def select(self, roadmap_id: str) -> dict[str, Any]:
        with self._lock:
            payload = self._read()
            item = payload['roadmaps'].get(str(roadmap_id))
            if not item or item.get('archived', False):
                raise RoadmapError('cannot select an archived or missing roadmap')
            payload['active_roadmap_id'] = str(roadmap_id)
            self._write(payload)
            return self._clone(item)

    def archive(self, roadmap_id: str) -> dict[str, Any]:
        with self._lock:
            payload = self._read()
            item = payload['roadmaps'].get(str(roadmap_id))
            if not item:
                raise RoadmapError('roadmap not found')
            item['archived'] = True
            item['updated_at'] = time.time()
            if payload.get('active_roadmap_id') == roadmap_id:
                payload['active_roadmap_id'] = next((rid for rid, value in payload['roadmaps'].items() if not value.get('archived', False) and rid != roadmap_id), None)
            self._write(payload)
            return self._clone(item)

    def delete(self, roadmap_id: str) -> None:
        with self._lock:
            payload = self._read()
            if roadmap_id not in payload['roadmaps']:
                raise RoadmapError('roadmap not found')
            del payload['roadmaps'][roadmap_id]
            if payload.get('active_roadmap_id') == roadmap_id:
                payload['active_roadmap_id'] = next((rid for rid, value in payload['roadmaps'].items() if not value.get('archived', False)), None)
            self._write(payload)

    def replace_tasks(self, roadmap_id: str, tasks: Sequence[Mapping[str, Any]], *, raw_text: str | None = None) -> dict[str, Any]:
        if len(tasks) > MAX_TASKS:
            raise RoadmapError('roadmap task count exceeds the configured limit')
        with self._lock:
            payload = self._read()
            item = payload['roadmaps'].get(str(roadmap_id))
            if not item or item.get('archived', False):
                raise RoadmapError('roadmap is missing or archived')
            item['tasks'] = [self._clone(value) for value in tasks if isinstance(value, Mapping)]
            if raw_text is not None:
                if len(raw_text) > MAX_RAW_CHARS:
                    raise RoadmapError('roadmap text exceeds the configured limit')
                item['raw_text'] = raw_text
            item['updated_at'] = time.time()
            self._write(payload)
            return self._clone(item)

    def combine(self, roadmap_ids: Sequence[str], name: str) -> dict[str, Any]:
        ids = list(dict.fromkeys(str(value) for value in roadmap_ids))
        if len(ids) < 2:
            raise RoadmapError('combine requires at least two roadmaps')
        sources = [self.get(value) for value in ids]
        combined: list[dict[str, Any]] = []
        task_sources: dict[str, str] = {}
        remaps: dict[tuple[str, str], str] = {}
        used: set[str] = set()
        for source in sources:
            for raw_task in source.get('tasks', []):
                if not isinstance(raw_task, Mapping):
                    continue
                old_id = str(raw_task.get('id', '')).strip()
                if not old_id:
                    continue
                new_id = old_id
                if new_id in used:
                    new_id = source['id'][:12] + '-' + old_id
                suffix = 2
                while new_id in used:
                    new_id = source['id'][:12] + '-' + old_id + '-' + str(suffix)
                    suffix += 1
                used.add(new_id)
                task_sources[new_id] = source['id']
                remaps[(source['id'], old_id)] = new_id
                task = self._clone(raw_task)
                task['id'] = new_id
                combined.append(task)
        for task in combined:
            owner_id = task_sources[task['id']]
            dependencies = task.get('depends_on', [])
            if isinstance(dependencies, list):
                task['depends_on'] = [remaps.get((owner_id, dep), dep) for dep in dependencies if isinstance(dep, str)]
        raw = '\n\n'.join(str(source.get('raw_text', '')).strip() for source in sources if str(source.get('raw_text', '')).strip())
        return self.create(name, raw_text=raw, tasks=combined, source_ids=ids)