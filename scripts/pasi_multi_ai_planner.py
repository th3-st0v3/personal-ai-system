from __future__ import annotations

import json
from typing import Any, Mapping

from scripts import pasi_hybrid_planner as hybrid
from scripts.pasi_dissection_adapter import dissect
from scripts.pasi_provider_router import call_gemini, call_groq

MAX_PROMPT_CHARS = 18_000

class MultiAIError(ValueError):
    pass

def _json_object(text: str) -> Mapping[str, Any]:
    candidate = text.strip()
    if candidate.startswith('```') and candidate.endswith('```'):
        lines = candidate.splitlines()
        candidate = '\n'.join(lines[1:-1]).strip()
        if candidate.startswith('json'):
            candidate = candidate[4:].lstrip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise MultiAIError('cloud planner returned invalid JSON') from exc
    if not isinstance(value, Mapping):
        raise MultiAIError('cloud planner response must be an object')
    return value

def architect_enrich(raw: str, deterministic: Mapping[str, Any]) -> dict[str, Any]:
    response = call_groq(
        'Convert this roadmap into atomic engineering task metadata. Preserve the exact supplied task IDs. Return JSON only with a tasks array; never add, remove, or rename IDs.\n\n' + json.dumps(deterministic, ensure_ascii=False) + '\n\nRAW ROADMAP:\n' + raw,
        45.0,
    )
    value = _json_object(response)
    tasks = value.get('tasks')
    expected = {str(item['id']) for item in deterministic.get('tasks', []) if isinstance(item, Mapping) and isinstance(item.get('id'), str)}
    received = {str(item.get('id')) for item in tasks if isinstance(item, Mapping)} if isinstance(tasks, list) else set()
    if received != expected:
        raise MultiAIError('Architect changed the deterministic task identity set')
    return {'schema_version': 1, 'tasks': [dict(item) for item in tasks], 'dissection': dict(deterministic.get('dissection', {}))}

def strategist_rank(tasks_payload: Mapping[str, Any]) -> tuple[str, ...]:
    response = call_gemini(
        'Reorder these already validated engineering tasks. Return JSON only as {"ranked_ids":[...]} and use every ID exactly once. Do not create tasks or change dependencies.\n\n' + json.dumps(tasks_payload, ensure_ascii=False),
        45.0,
    )
    value = _json_object(response)
    ranked = value.get('ranked_ids')
    if not isinstance(ranked, list) or not all(isinstance(item, str) for item in ranked):
        raise MultiAIError('Strategist must return ranked_ids as strings')
    return tuple(ranked)

def build_coding_prompt(task: Mapping[str, Any]) -> str:
    task_id = str(task.get('id', '')).strip()
    title = str(task.get('title', '')).strip()
    objective = str(task.get('objective', '')).strip()
    criteria = task.get('acceptance_criteria', [])
    verification = task.get('verification', [])
    if not task_id or not title:
        raise MultiAIError('cannot generate a prompt for an invalid task')
    criteria_lines = '\n'.join('- ' + str(item) for item in criteria if str(item).strip())
    verification_lines = '\n'.join('- ' + str(item) for item in verification if str(item).strip())
    prompt = (
        'PASI TASK ' + task_id + '\n'
        'Work only on this task until its acceptance criteria are satisfied.\n\n'
        'TITLE:\n' + title + '\n\n'
        'OBJECTIVE:\n' + objective + '\n\n'
        'ACCEPTANCE CRITERIA:\n' + (criteria_lines or '- Complete the stated objective.') + '\n\n'
        'VERIFICATION:\n' + (verification_lines or '- Run deterministic repository validation.') + '\n\n'
        'CONSTRAINTS:\n'
        '- Preserve PASI safety and protected-path rules.\n'
        '- Do not broaden permissions or introduce a second scheduler.\n'
        '- Make the smallest complete, testable change.\n'
        '- Report exactly what changed and what verification actually ran.'
    )
    return prompt[:MAX_PROMPT_CHARS]

def plan(raw: str, *, use_cloud: bool = True) -> dict[str, Any]:
    deterministic = dissect(raw)
    architect_used = False
    strategist_used = False
    payload = deterministic
    if use_cloud:
        try:
            enriched = architect_enrich(raw, deterministic)
            task_specs = [
                hybrid.task_from_mapping(item)
                for item in enriched.get('tasks', [])
                if isinstance(item, Mapping)
            ]
            if not task_specs:
                raise MultiAIError('Architect returned no valid task specifications')
            payload = enriched
            architect_used = True
            if len(task_specs) > 1:
                try:
                    ranking = strategist_rank({'tasks': [dict(item) for item in payload['tasks']]})
                    ordered = hybrid.validate_ai_ranking(tuple(task_specs), ranking)
                    by_id = {item['id']: item for item in payload['tasks']}
                    payload = dict(payload)
                    payload['tasks'] = [by_id[item.id] for item in ordered]
                    strategist_used = True
                except Exception:
                    pass
        except Exception:
            payload = deterministic
    payload = dict(payload)
    payload['planning'] = {'architect': architect_used, 'strategist': strategist_used, 'fallback': not (architect_used or strategist_used)}
    return payload

def next_prompt(tasks: list[Mapping[str, Any]], *, ledger: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    parsed = [hybrid.task_from_mapping(item) for item in tasks if isinstance(item, Mapping)]
    eligible = hybrid.eligible_tasks(tuple(parsed), ledger or {})
    if not eligible:
        raise MultiAIError('no eligible roadmap task is available')
    eligible_ids = {item.id for item in eligible}
    preferred = tuple(item for item in parsed if item.id in eligible_ids)
    ordered = preferred or hybrid.deterministic_rank(eligible, parsed, ledger or {})
    selected = ordered[0]
    return {
        'task_id': selected.id,
        'mode': 'preferred_order' if preferred else 'deterministic',
        'ranked_ids': [item.id for item in ordered],
        'prompt': build_coding_prompt(selected.to_dict()),
    }

if __name__ == '__main__':
    raise SystemExit('use the bridge or import this module')