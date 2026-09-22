from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

MAX_INPUT_CHARS = 500_000
MAX_TASKS = 512
MAX_TEXT_CHARS = 4_000
TASK_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|\[[ xX]\]\s+)(?P<text>.+?)\s*$")
DEP_RE = re.compile(r"\b(?:depends on|requires?|after)\s*[:=-]?\s*([^.;]+)", re.IGNORECASE)

class DissectionError(ValueError):
    pass

@dataclass(frozen=True)
class Candidate:
    id: str
    title: str
    objective: str
    source_line: int
    depends_on: tuple[str, ...]

def _compact(value: str, limit: int = MAX_TEXT_CHARS) -> str:
    value = " ".join(str(value).split()).strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"

def _slug(value: str, index: int) -> str:
    stem = "-".join(re.findall(r"[A-Za-z0-9]+", value.casefold())[:8]) or "task"
    return f"roadmap-{index:03d}-{stem}"[:90]

def _parse_dependencies(text: str, known: Mapping[str, str]) -> tuple[str, ...]:
    match = DEP_RE.search(text)
    if not match:
        return ()
    found: list[str] = []
    for piece in re.split(r",|/|\band\b", match.group(1), flags=re.IGNORECASE):
        candidate = piece.strip(" `()")
        for key, task_id in known.items():
            if candidate.casefold() == key.casefold() or candidate.casefold() == task_id.casefold():
                if task_id not in found:
                    found.append(task_id)
                break
    return tuple(found)

def deconstruct(raw: str) -> tuple[Candidate, ...]:
    text = raw.strip()
    if not text:
        raise DissectionError("roadmap is empty")
    if len(text) > MAX_INPUT_CHARS:
        raise DissectionError("roadmap exceeds the 500,000 character input limit")
    candidates: list[Candidate] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        match = TASK_RE.match(line)
        if not match:
            continue
        title = _compact(match.group("text"), 240)
        if len(title) >= 3:
            candidates.append(Candidate(_slug(title, len(candidates) + 1), title, title, line_number, ()))
    if not candidates:
        for index, paragraph in enumerate((p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()), 1):
            title = _compact(paragraph.splitlines()[0], 240)
            if len(title) >= 3:
                candidates.append(Candidate(_slug(title, index), title, _compact(paragraph), index, ()))
    if not candidates:
        raise DissectionError("no task-like roadmap entries were detected")
    return tuple(candidates[:MAX_TASKS])

def map_dependencies(candidates: Iterable[Candidate]) -> tuple[Candidate, ...]:
    values = tuple(candidates)
    aliases: dict[str, str] = {}
    for item in values:
        aliases[item.id] = item.id
        aliases[item.title] = item.id
        explicit = re.match(r"\s*((?:task|t)[-_ ]?[A-Za-z0-9][A-Za-z0-9._-]{0,63})\s*[:.)-]", item.title, re.IGNORECASE)
        if explicit:
            aliases[explicit.group(1)] = item.id
    mapped = tuple(Candidate(i.id, i.title, i.objective, i.source_line, _parse_dependencies(i.title, aliases)) for i in values)
    by_id = {i.id: i for i in mapped}
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise DissectionError(f"dependency cycle detected at {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dep in by_id[task_id].depends_on:
            if dep not in by_id:
                raise DissectionError(f"dependency references unknown task {dep}")
            visit(dep)
        visiting.remove(task_id)
        visited.add(task_id)
    for item in mapped:
        visit(item.id)
    return mapped

def compile_json(candidates: Iterable[Candidate]) -> dict[str, Any]:
    tasks = []
    for index, item in enumerate(candidates, 1):
        tasks.append({
            "id": item.id,
            "title": item.title,
            "objective": item.objective,
            "depends_on": list(item.depends_on),
            "acceptance_criteria": [f"Complete the stated roadmap objective for '{item.title}'."],
            "verification": ["Run deterministic task validation and inspect repository progress."],
            "allowed_paths": [],
            "priority": max(0, 1000 - index),
            "splittable": len(item.objective) > 180,
            "estimated_size": "medium" if len(item.objective) > 100 else "small",
            "phase": "automation",
            "status": "pending",
            "provenance": {"source_line": item.source_line},
        })
    return {"schema_version": 1, "tasks": tasks}

def dissect(raw: str, *, ai_json: Callable[[str], Mapping[str, Any]] | None = None) -> dict[str, Any]:
    first = deconstruct(raw)
    second = map_dependencies(first)
    payload = compile_json(second)
    if ai_json is not None:
        enriched = dict(ai_json(json.dumps(payload, ensure_ascii=False)))
        items = enriched.get("tasks")
        expected = {task["id"] for task in payload["tasks"]}
        if not isinstance(items, list) or {str(item.get("id")) for item in items if isinstance(item, dict)} != expected:
            raise DissectionError("AI dissection must preserve the deterministic task identity set")
        payload = enriched
    payload["dissection"] = {"passes": [
        {"name": "deconstruct", "status": "complete", "progress": 33},
        {"name": "dependencies", "status": "complete", "progress": 66},
        {"name": "json_compile", "status": "complete", "progress": 100},
    ], "task_count": len(payload["tasks"]), "ai_enrichment_used": ai_json is not None}
    return payload

def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic three-pass PASI roadmap dissection adapter.")
    parser.add_argument("roadmap")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = dissect(open(args.roadmap, encoding="utf-8").read())
    encoded = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(encoded)
    else:
        print(encoded, end="")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())