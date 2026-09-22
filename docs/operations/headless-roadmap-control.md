# PASI Headless Roadmap Control

The native extension can manage roadmap state without the Control Center UI. The authenticated localhost bridge owns durable roadmap storage; the extension service worker exposes a narrow request API.

## Roadmap lifecycle

- GET /roadmaps lists active roadmaps without returning raw roadmap text.
- GET /roadmap/active returns the selected roadmap and its tasks.
- POST /roadmaps with action=create creates and selects a roadmap.
- POST /roadmap/select changes the active roadmap.
- POST /roadmap/archive hides an old roadmap from normal selection while retaining it for history.
- POST /roadmap/delete permanently removes a roadmap.
- POST /roadmap/combine creates a new roadmap from two or more active roadmaps and remaps colliding task IDs/dependencies.
- POST /roadmap/dissect runs deterministic roadmap dissection and optionally bounded Groq/Gemini enrichment using credentials held only in the bridge environment.
- POST /roadmap/next-prompt produces the next dependency-eligible coding prompt.
- POST /roadmap/next-operation creates an idempotent ChatGPT prompt operation bound to the selected roadmap/task.

## Stale-task prevention

Generated operations carry both roadmap_id and roadmap_task_id. A task is marked completed only after the browser bridge accepts verified nonblank response evidence. Therefore the next selection does not repeatedly return an already-completed task.

Archiving a roadmap removes it from the normal active set. Combining roadmaps creates a fresh derived roadmap instead of mutating the source roadmaps.

## Cloud chain

1. Deterministic dissection establishes the initial task identity and dependency envelope.
2. Groq may enrich task metadata without changing the deterministic identity set.
3. Gemini may rank the already-validated tasks.
4. The Hybrid Planner performs final dependency/eligibility selection.
5. PASI generates a bounded coding prompt and queues it for the native ChatGPT controller.

Any unavailable or invalid cloud response falls back to deterministic planning. API keys are environment-only and are never written to extension storage or bridge roadmap responses.

## Self-hosted runner

scripts/install_pasi_self_hosted_runner.sh registers a GitHub Actions runner in WSL using the short-lived token supplied in PASI_RUNNER_TOKEN. The script defaults to labels pasi-desktop,pasi-wsl,pasi-capabilities-v1 and never persists the registration token.

Use the normal GitHub repository Settings → Actions → Runners → New self-hosted runner flow to obtain the current short-lived registration token. Do not commit or store that token in the repository.