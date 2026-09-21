from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

SCHEMA_VERSION = 1
MAX_TASKS = 512
MAX_ID_CHARS = 160
MAX_TEXT_CHARS = 8000
MAX_CRITERIA = 32
MAX_CHILDREN = 16
DEFAULT_AI_TIMEOUT_SECONDS = 1.5

Ranker = Callable[[Sequence["TaskSpec"]], Sequence[str]]


class PlannerError(ValueError):
    pass


@dataclass(frozen=True)
class TaskSpec:
    id: str
    title: str
    objective: str
    depends_on: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ()
    priority: int = 0
    splittable: bool = False
    estimated_size: str = "medium"
    phase: str = "engineering_os"
    status: str = "pending"
    decomposition_parent: str = ""
    decomposed_children: tuple[str, ...] = ()

    def execution_text(self) -> str:
        lines = [f"TITLE: {self.title}", f"OBJECTIVE: {self.objective}"]
        if self.acceptance_criteria:
            lines.append("ACCEPTANCE CRITERIA:")
            lines.extend(f"- {item}" for item in self.acceptance_criteria)
        if self.verification:
            lines.append("VERIFICATION:")
            lines.extend(f"- {item}" for item in self.verification)
        if self.allowed_paths:
            lines.append("SCOPE:")
            lines.append("Allowed: " + ", ".join(self.allowed_paths))
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "objective": self.objective,
            "depends_on": list(self.depends_on),
            "acceptance_criteria": list(self.acceptance_criteria),
            "verification": list(self.verification),
            "allowed_paths": list(self.allowed_paths),
            "priority": self.priority,
            "splittable": self.splittable,
            "estimated_size": self.estimated_size,
            "phase": self.phase,
            "status": self.status,
            "decomposition_parent": self.decomposition_parent,
            "decomposed_children": list(self.decomposed_children),
        }


@dataclass(frozen=True)
class PlannerDecision:
    selected: TaskSpec | None
    eligible_ids: tuple[str, ...]
    mode: str
    reason: str
    ai_used: bool = False


def _text(value: object, *, field: str, limit: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str):
        raise PlannerError(f"{field} must be a string")
    result = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not result:
        raise PlannerError(f"{field} must not be empty")
    if len(result) > limit:
        raise PlannerError(f"{field} exceeds {limit} characters")
    if any(ord(char) < 32 and char not in "\n\t" for char in result):
        raise PlannerError(f"{field} contains control characters")
    return result


def _string_list(value: object, *, field: str, limit: int = MAX_CRITERIA) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise PlannerError(f"{field} must be a list")
    if len(value) > limit:
        raise PlannerError(f"{field} contains too many entries")
    return tuple(_text(item, field=f"{field} item", limit=2000) for item in value)


def _priority(value: object) -> int:
    if isinstance(value, bool):
        raise PlannerError("priority must be an integer")
    try:
        result = int(value) if value is not None else 0
    except (TypeError, ValueError) as exc:
        raise PlannerError("priority must be an integer") from exc
    return max(-1000, min(1000, result))


def task_from_mapping(raw: Mapping[str, Any], *, default_phase: str = "engineering_os") -> TaskSpec:
    task_id = _text(raw.get("id"), field="id", limit=MAX_ID_CHARS)
    title = _text(raw.get("title"), field=f"{task_id}.title", limit=2000)
    objective = _text(raw.get("objective"), field=f"{task_id}.objective")
    depends_on = _string_list(raw.get("depends_on", []), field=f"{task_id}.depends_on", limit=64)
    acceptance = _string_list(raw.get("acceptance_criteria", []), field=f"{task_id}.acceptance_criteria")
    verification = _string_list(raw.get("verification", []), field=f"{task_id}.verification")
    allowed_paths = _string_list(raw.get("allowed_paths", []), field=f"{task_id}.allowed_paths", limit=128)
    phase = str(raw.get("phase", default_phase)).strip() or default_phase
    status = str(raw.get("status", "pending")).strip().casefold() or "pending"
    if status not in {"pending", "blocked", "cancelled", "decomposed"}:
        raise PlannerError(f"{task_id}.status is invalid")
    estimated_size = str(raw.get("estimated_size", "medium")).strip().casefold() or "medium"
    if estimated_size not in {"small", "medium", "large", "very_large"}:
        raise PlannerError(f"{task_id}.estimated_size is invalid")
    splittable = raw.get("splittable", False)
    if not isinstance(splittable, bool):
        raise PlannerError(f"{task_id}.splittable must be boolean")
    decomposition_parent = str(raw.get("decomposition_parent", "")).strip()
    raw_children = raw.get("decomposed_children", [])
    decomposed_children = _string_list(
        raw_children,
        field=f"{task_id}.decomposed_children",
        limit=MAX_CHILDREN,
    )
    if status != "decomposed" and decomposed_children:
        raise PlannerError(f"{task_id}.decomposed_children requires decomposed status")
    return TaskSpec(
        id=task_id,
        title=title,
        objective=objective,
        depends_on=depends_on,
        acceptance_criteria=acceptance,
        verification=verification,
        allowed_paths=allowed_paths,
        priority=_priority(raw.get("priority", 0)),
        splittable=splittable,
        estimated_size=estimated_size,
        phase=phase,
        status=status,
        decomposition_parent=decomposition_parent,
        decomposed_children=decomposed_children,
    )


def validate_roadmap(tasks: Sequence[TaskSpec]) -> tuple[TaskSpec, ...]:
    if not tasks:
        raise PlannerError("roadmap must contain at least one task")
    if len(tasks) > MAX_TASKS:
        raise PlannerError(f"roadmap exceeds {MAX_TASKS} tasks")
    by_id: dict[str, TaskSpec] = {}
    for task in tasks:
        if task.id in by_id:
            raise PlannerError(f"duplicate task id: {task.id}")
        by_id[task.id] = task

    for task in tasks:
        if task.decomposition_parent:
            parent = by_id.get(task.decomposition_parent)
            if parent is None:
                raise PlannerError(
                    f"{task.id} references unknown decomposition parent {task.decomposition_parent}"
                )
            if task.id not in parent.decomposed_children:
                raise PlannerError(
                    f"{task.id} is missing from decomposition parent {parent.id}"
                )
        for child_id in task.decomposed_children:
            child = by_id.get(child_id)
            if child is None:
                raise PlannerError(
                    f"{task.id} references unknown decomposition child {child_id}"
                )
            if child.decomposition_parent != task.id:
                raise PlannerError(
                    f"{task.id} decomposition child {child_id} has the wrong parent"
                )
        for dependency in task.depends_on:
            if dependency not in by_id:
                raise PlannerError(f"{task.id} depends on unknown task {dependency}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise PlannerError(f"dependency cycle detected at {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in by_id[task_id].depends_on:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task in tasks:
        visit(task.id)
    return tuple(tasks)


def load_roadmap(path: Path) -> tuple[TaskSpec, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PlannerError(f"could not read roadmap: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PlannerError(f"roadmap is not valid JSON: {path}") from exc

    if isinstance(raw, list):
        raw_tasks = raw
    elif isinstance(raw, dict):
        if int(raw.get("schema_version", SCHEMA_VERSION)) != SCHEMA_VERSION:
            raise PlannerError("unsupported roadmap schema_version")
        raw_tasks = raw.get("tasks")
    else:
        raise PlannerError("roadmap must be a JSON object or task list")
    if not isinstance(raw_tasks, list):
        raise PlannerError("roadmap.tasks must be a list")

    tasks: list[TaskSpec] = []
    for item in raw_tasks:
        if not isinstance(item, dict):
            raise PlannerError("every roadmap task must be an object")
        tasks.append(task_from_mapping(item))
    return validate_roadmap(tasks)


def load_roadmap_with_overlay(
    source_path: Path,
    overlay_path: Path | None = None,
) -> tuple[TaskSpec, ...]:
    tasks = list(load_roadmap(source_path))
    if overlay_path is None or not overlay_path.is_file():
        return tuple(tasks)
    try:
        raw = json.loads(overlay_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlannerError(f"invalid roadmap decomposition overlay: {overlay_path}") from exc
    if not isinstance(raw, dict) or int(raw.get("schema_version", 0)) != SCHEMA_VERSION:
        raise PlannerError("invalid roadmap decomposition overlay schema")
    decompositions = raw.get("decompositions", {})
    generated = raw.get("generated_tasks", [])
    if not isinstance(decompositions, dict) or not isinstance(generated, list):
        raise PlannerError("invalid roadmap decomposition overlay")
    decomposed_ids = {
        str(parent_id)
        for parent_id, info in decompositions.items()
        if isinstance(info, dict) and info.get("status") == "decomposed"
    }
    updated: list[TaskSpec] = []
    for task in tasks:
        if task.id in decomposed_ids:
            info = decompositions[task.id]
            children = info.get("children", [])
            if not isinstance(children, list) or not all(isinstance(item, str) for item in children):
                raise PlannerError(f"invalid decomposition children for {task.id}")
            updated.append(
                TaskSpec(
                    id=task.id,
                    title=task.title,
                    objective=task.objective,
                    depends_on=task.depends_on,
                    acceptance_criteria=task.acceptance_criteria,
                    verification=task.verification,
                    allowed_paths=task.allowed_paths,
                    priority=task.priority,
                    splittable=task.splittable,
                    estimated_size=task.estimated_size,
                    phase=task.phase,
                    status="decomposed",
                    decomposition_parent=task.decomposition_parent,
                    decomposed_children=tuple(children),
                )
            )
        else:
            updated.append(task)
    for item in generated:
        if not isinstance(item, dict):
            raise PlannerError("generated roadmap task must be an object")
        updated.append(task_from_mapping(item))
    return validate_roadmap(updated)


def save_decomposition_overlay(
    path: Path,
    *,
    parent: TaskSpec,
    children: Sequence[TaskSpec],
) -> None:
    children = validate_decomposition(parent, children)
    decompositions: dict[str, dict[str, Any]] = {}
    generated: dict[str, dict[str, Any]] = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PlannerError(f"invalid existing decomposition overlay: {path}") from exc
        if not isinstance(raw, dict) or int(raw.get("schema_version", 0)) != SCHEMA_VERSION:
            raise PlannerError("invalid existing decomposition overlay schema")
        raw_decompositions = raw.get("decompositions", {})
        raw_generated = raw.get("generated_tasks", [])
        if isinstance(raw_decompositions, dict):
            decompositions = {
                str(key): dict(item)
                for key, item in raw_decompositions.items()
                if isinstance(item, dict)
            }
        if isinstance(raw_generated, list):
            generated = {
                str(item["id"]): dict(item)
                for item in raw_generated
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
    decompositions[parent.id] = {
        "status": "decomposed",
        "children": [child.id for child in children],
    }
    for child in children:
        generated[child.id] = child.to_dict()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "decompositions": decompositions,
        "generated_tasks": list(generated.values()),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def ledger_task_status(ledger: Mapping[str, Mapping[str, Any]], task: TaskSpec) -> str:
    for entry in ledger.values():
        if str(entry.get("task_id", "")).strip() == task.id:
            return str(entry.get("status", "")).strip().casefold()
    canonical = " ".join(task.execution_text().split())
    for entry in ledger.values():
        if " ".join(str(entry.get("task", "")).split()) == canonical:
            return str(entry.get("status", "")).strip().casefold()
    return ""


def eligible_tasks(
    tasks: Sequence[TaskSpec],
    ledger: Mapping[str, Mapping[str, Any]],
    *,
    phase: str | None = None,
) -> tuple[TaskSpec, ...]:
    by_id = {task.id: task for task in tasks}
    memo: dict[str, bool] = {}
    visiting: set[str] = set()

    def satisfied(task_id: str) -> bool:
        if task_id in memo:
            return memo[task_id]
        if task_id in visiting:
            return False
        task = by_id.get(task_id)
        if task is None:
            return False
        status = ledger_task_status(ledger, task) or task.status
        if status == "completed":
            memo[task_id] = True
            return True
        if status == "decomposed":
            visiting.add(task_id)
            result = bool(task.decomposed_children) and all(
                satisfied(child_id) for child_id in task.decomposed_children
            )
            visiting.remove(task_id)
            memo[task_id] = result
            return result
        memo[task_id] = False
        return False

    result: list[TaskSpec] = []
    for task in tasks:
        if phase is not None and task.phase != phase:
            continue
        status = ledger_task_status(ledger, task) or task.status
        if status in {"completed", "cancelled", "in_progress"}:
            continue
        if status == "blocked":
            continue
        if status == "decomposed" and satisfied(task.id):
            continue
        if task.decomposition_parent:
            parent = by_id.get(task.decomposition_parent)
            parent_status = ledger_task_status(ledger, parent) if parent is not None else ""
            parent_status = parent_status or (parent.status if parent is not None else "")
            if parent is None or parent_status != "decomposed" or task.id not in parent.decomposed_children:
                continue
        if any(not satisfied(dependency) for dependency in task.depends_on):
            continue
        result.append(task)
    return tuple(result)


def _unblock_count(task: TaskSpec, tasks: Sequence[TaskSpec], completed: set[str]) -> int:
    return sum(1 for other in tasks if task.id in other.depends_on and other.id not in completed)


def deterministic_rank(
    candidates: Sequence[TaskSpec],
    tasks: Sequence[TaskSpec],
    ledger: Mapping[str, Mapping[str, Any]],
) -> tuple[TaskSpec, ...]:
    completed = {task.id for task in tasks if ledger_task_status(ledger, task) == "completed"}
    return tuple(sorted(
        candidates,
        key=lambda task: (
            -task.priority,
            -_unblock_count(task, tasks, completed),
            task.estimated_size == "very_large",
            task.estimated_size == "large",
            task.id,
        ),
    ))


def validate_ai_ranking(
    candidates: Sequence[TaskSpec],
    ranking: Iterable[str],
) -> tuple[TaskSpec, ...]:
    by_id = {task.id: task for task in candidates}
    ordered: list[TaskSpec] = []
    seen: set[str] = set()
    for item in ranking:
        task_id = str(item).strip()
        if task_id not in by_id or task_id in seen:
            raise PlannerError("AI planner returned an invalid or duplicate task id")
        seen.add(task_id)
        ordered.append(by_id[task_id])
    if seen != set(by_id):
        raise PlannerError("AI planner omitted one or more eligible task ids")
    return tuple(ordered)


def _http_json(url: str, payload: Mapping[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(1_000_001)
    except urllib.error.HTTPError:
        raise
    if len(body) > 1_000_000:
        raise PlannerError("planner AI response exceeded size limit")
    decoded = json.loads(body.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise PlannerError("planner AI response must be an object")
    return decoded


def _model_json(text: str) -> Any:
    candidate = text.strip()
    if candidate.startswith(chr(96) * 3) and candidate.endswith(chr(96) * 3):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].lstrip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise PlannerError("planner AI returned invalid JSON") from exc


def _extract_ollama_content(payload: Mapping[str, Any]) -> str:
    message = payload.get("message")
    if not isinstance(message, Mapping):
        raise PlannerError("Ollama planner response has no message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise PlannerError("Ollama planner response has no content")
    return content.strip()


def _ollama_call(
    *,
    system_prompt: str,
    user_payload: Mapping[str, Any],
    timeout_seconds: float,
    base_url: str | None = None,
    model: str | None = None,
) -> Any:
    selected_model = (
        model
        or os.environ.get("PASI_PLANNER_MODEL")
        or os.environ.get("OLLAMA_MODEL")
        or ""
    ).strip()
    if not selected_model:
        raise PlannerError("no planner model configured")
    url = (
        base_url
        or os.environ.get("PASI_PLANNER_BASE_URL")
        or "http://127.0.0.1:11434"
    ).rstrip("/") + "/api/chat"
    payload = {
        "model": selected_model,
        "stream": False,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
    }
    return _model_json(
        _extract_ollama_content(_http_json(url, payload, timeout_seconds))
    )


def ollama_ranker(
    candidates: Sequence[TaskSpec],
    *,
    timeout_seconds: float = DEFAULT_AI_TIMEOUT_SECONDS,
    base_url: str | None = None,
    model: str | None = None,
) -> tuple[str, ...]:
    raw = _ollama_call(
        system_prompt="Rank only eligible engineering tasks supplied by PASI. Return JSON only.",
        user_payload={
            "instruction": "Return ranked_ids from first to last. Do not add, remove, rename, or rewrite tasks.",
            "tasks": [
                {
                    "id": task.id,
                    "title": task.title,
                    "objective": task.objective,
                    "priority": task.priority,
                    "estimated_size": task.estimated_size,
                }
                for task in candidates
            ],
        },
        timeout_seconds=timeout_seconds,
        base_url=base_url,
        model=model,
    )
    if isinstance(raw, dict):
        raw = raw.get("ranked_ids")
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise PlannerError("planner AI must return ranked_ids as a string list")
    return tuple(raw)


def select_task(
    tasks: Sequence[TaskSpec],
    ledger: Mapping[str, Mapping[str, Any]],
    *,
    phase: str | None = None,
    ai_ranker: Ranker | None = None,
) -> PlannerDecision:
    eligible = eligible_tasks(tasks, ledger, phase=phase)
    if not eligible:
        return PlannerDecision(None, (), "none", "no eligible task")
    deterministic = deterministic_rank(eligible, tasks, ledger)
    if len(deterministic) == 1:
        return PlannerDecision(
            deterministic[0],
            tuple(task.id for task in deterministic),
            "deterministic",
            "only eligible task",
        )
    if ai_ranker is None:
        return PlannerDecision(
            deterministic[0],
            tuple(task.id for task in deterministic),
            "deterministic",
            "AI ranking unavailable; deterministic fallback",
        )
    try:
        ai_order = validate_ai_ranking(eligible, ai_ranker(eligible))
    except (PlannerError, OSError, TimeoutError, urllib.error.URLError, ValueError):
        return PlannerDecision(
            deterministic[0],
            tuple(task.id for task in deterministic),
            "deterministic_fallback",
            "AI ranking invalid or unavailable",
        )
    return PlannerDecision(
        ai_order[0],
        tuple(task.id for task in ai_order),
        "ai_rank",
        "AI ranked only deterministic eligible tasks",
        True,
    )


def validate_decomposition(parent: TaskSpec, children: Sequence[TaskSpec]) -> tuple[TaskSpec, ...]:
    if not parent.splittable:
        raise PlannerError(f"task {parent.id} is not marked splittable")
    if not 2 <= len(children) <= MAX_CHILDREN:
        raise PlannerError("decomposition must produce between two and sixteen child tasks")
    ids = {child.id for child in children}
    if len(ids) != len(children):
        raise PlannerError("decomposition child IDs must be unique")
    if parent.id in ids:
        raise PlannerError("decomposition child cannot reuse parent id")
    for child in children:
        if child.status != "pending":
            raise PlannerError(f"decomposition child {child.id} must start pending")
        if child.status != "pending":
            raise PlannerError(f"decomposition child {child.id} must start pending")
        if child.decomposition_parent != parent.id:
            raise PlannerError(f"decomposition child {child.id} must identify its parent")
        if not child.acceptance_criteria or not child.verification:
            raise PlannerError(f"decomposition child {child.id} is incomplete")
        if child.phase != parent.phase:
            raise PlannerError(f"decomposition child {child.id} changed phase")
        if parent.allowed_paths:
            parent_paths = tuple(parent.allowed_paths)
            for path in child.allowed_paths:
                if not any(
                    path == allowed or path.startswith(allowed.rstrip("/") + "/")
                    for allowed in parent_paths
                ):
                    raise PlannerError(f"decomposition child {child.id} escapes parent scope")
        dependencies = set(child.depends_on)
        allowed_dependencies = set(parent.depends_on) | ids
        if dependencies - allowed_dependencies:
            raise PlannerError(f"decomposition child {child.id} has an external dependency")
        if parent.id in dependencies:
            raise PlannerError(f"decomposition child {child.id} must not depend on the decomposed parent")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise PlannerError(f"decomposition dependency cycle detected at {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        task = next(child for child in children if child.id == task_id)
        for dependency in task.depends_on:
            if dependency in ids:
                visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for child in children:
        visit(child.id)
    return tuple(children)


def ai_decompose_with_ollama(
    task: TaskSpec,
    *,
    timeout_seconds: float = DEFAULT_AI_TIMEOUT_SECONDS,
    base_url: str | None = None,
    model: str | None = None,
) -> tuple[TaskSpec, ...]:
    raw = _ollama_call(
        system_prompt="Decompose only the supplied engineering task. Return JSON only.",
        user_payload={
            "instruction": "Return 2 to 16 independently verifiable child tasks. Keep the parent's prerequisites, stay within its scope, and include acceptance criteria and verification. Do not make a child depend on the decomposed parent.",
            "parent": task.to_dict(),
        },
        timeout_seconds=timeout_seconds,
        base_url=base_url,
        model=model,
    )
    if isinstance(raw, dict):
        raw = raw.get("tasks")
    if not isinstance(raw, list):
        raise PlannerError("planner AI decomposition must return a tasks list")
    children: list[TaskSpec] = []
    for item in raw:
        if not isinstance(item, dict):
            raise PlannerError("planner AI returned an invalid child task")
        children.append(task_from_mapping(item, default_phase=task.phase))
    return validate_decomposition(task, children)
