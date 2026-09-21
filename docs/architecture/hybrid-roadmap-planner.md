# PASI Hybrid Roadmap Planner

PASI accepts a structured roadmap and selects exactly one executable task at a time.

## Planning policy

The planner always validates the roadmap and computes deterministic eligibility before an AI is consulted.

Deterministic rules reject duplicate IDs, unknown dependencies, dependency cycles, blocked tasks, incomplete prerequisites, active/in-progress tasks, and invalid decomposition relationships. A decomposed parent is not considered satisfied until every generated child is verified complete.

When more than one task is eligible, PASI may optionally ask a local planner model to rank those eligible tasks. The model receives only the eligible candidates and must return exactly the same task IDs. Invalid, incomplete, unavailable, or timed-out AI output falls back to deterministic ranking.

AI decomposition is also optional. A task must be explicitly marked `splittable` and `large` or `very_large`. Generated children must be finite, verifiable, remain in the parent scope and phase, identify their parent, inherit the parent's prerequisites, and form an acyclic child graph. Accepted decompositions are persisted in the runtime overlay so a restart does not discard them.

The executor model never selects the next task. After verification and ledger update, the scheduler recomputes eligibility and selects the next task.

## Roadmap format

A roadmap is JSON with `schema_version: 1` and a `tasks` array. Each task requires:

- `id`
- `title`
- `objective`
- `acceptance_criteria`
- `verification`

Optional fields include `depends_on`, `allowed_paths`, `priority`, `splittable`, `estimated_size`, `phase`, and `status`.

Example:

```json
{
  "schema_version": 1,
  "tasks": [
    {
      "id": "example.foundation",
      "title": "Build the foundation",
      "objective": "Implement the prerequisite capability.",
      "acceptance_criteria": ["The capability works."],
      "verification": ["Run the targeted test."],
      "priority": 100,
      "phase": "engineering_os",
      "status": "pending"
    },
    {
      "id": "example.followup",
      "title": "Build the follow-up",
      "objective": "Implement work that requires the foundation.",
      "depends_on": ["example.foundation"],
      "acceptance_criteria": ["The follow-up works."],
      "verification": ["Run the targeted test."],
      "phase": "engineering_os",
      "status": "pending"
    }
  ]
}
```
## Running a roadmap

The 168-hour launcher uses `roadmaps/pasi-default.json` by default.

A different roadmap can be supplied with:

```bash
PASI_ROADMAP_PATH=/path/to/roadmap.json bash scripts/start_pasi_168h.sh
```
The engine also accepts the explicit form:

```bash
python scripts/pasi_overnight_engine_v2.py --hours 168 --roadmap /path/to/roadmap.json
```
## Optional AI planning

AI ranking is opt-in so the normal response-completion-to-next-prompt path does not wait on a planner model:

```bash
export PASI_PLANNER_AI_RANK=true
export PASI_PLANNER_MODEL=qwen3:8b
```
AI decomposition is independently opt-in:

```bash
export PASI_PLANNER_AI_DECOMPOSE=true
```
Without either setting, PASI remains fully deterministic. The AI is never required for dependency correctness or task sequencing safety.

## Runtime state

The selected roadmap path and stable current task ID are stored in the unattended state. Completed task records also persist the task ID, commit, phase, and verification evidence. Planner decisions are emitted to the runtime event log with the eligible task IDs, selected task ID, mode, and reason.
