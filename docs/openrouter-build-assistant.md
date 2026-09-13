# OpenRouter Build Assistant

This stage adds a **supervised** long-running engineering build assistant. It uses OpenRouter's free-model router by default, keeps progress in a local JSON checkpoint, handles rate limits, and places model-generated changes in an approval queue instead of writing them directly into the repository.

OpenRouter currently lists `openrouter/free` as a zero-price router for available free models. Its current free plan lists a 50-request/day limit, so this worker defaults to 45 requests/day and spaces cycles about 35 minutes apart. Limits can change; check the OpenRouter pricing page before changing these values.

## What this means in plain English

The worker is a second AI helper for the project. It can look at a small project roadmap, ask a model for the **next single improvement**, and remember the answer.

It does **not** silently edit your code, run arbitrary shell commands, deploy software, trade, move money, or access credentials.

That is intentional. The useful loop is:

```text
AI proposes one change
        ↓
save proposal
        ↓
you review it
        ↓
you approve/apply it
        ↓
tests run
        ↓
next cycle learns from the result
```

## First-time setup

1. Create an OpenRouter API key in your OpenRouter account.
2. In the WSL terminal for this project, set it as an environment variable:

```bash
export OPENROUTER_API_KEY='paste-your-key-here'
```

Do not put the key into Python source code, Git, `.env` files committed to the repository, or screenshots.

3. Run one safe test cycle:

```bash
cd ~/workspace/personal-ai-system
PYTHONPATH=src python scripts/openrouter_build_loop.py --once
```

The first run creates:

```text
.runtime/ai_os_project_state.json
```

That file is local runtime state and is intentionally not part of the application source tree.

## See what the assistant proposed

After a cycle:

```bash
python -m json.tool .runtime/ai_os_project_state.json
```

Look for:

```text
approval_queue
```

Each entry contains the reason for the proposal, target file, generated code, and `pending_review` status.

Nothing is applied automatically.

## Run continuously

For the free tier, use the default budget and interval:

```bash
PYTHONPATH=src python scripts/openrouter_build_loop.py
```

The worker automatically stops when its daily request budget is reached and keeps its checkpoint so it can be resumed later.

## Useful controls

Use a different model:

```bash
PYTHONPATH=src python scripts/openrouter_build_loop.py --model openrouter/free --once
```

Use fewer requests:

```bash
PYTHONPATH=src python scripts/openrouter_build_loop.py --max-daily-requests 10
```

Test faster locally without trying to consume the whole daily allowance:

```bash
PYTHONPATH=src python scripts/openrouter_build_loop.py --once --min-interval-seconds 30
```

The minimum interval is deliberately prevented from becoming zero so an accidental tight loop cannot hammer the API.

## Current roadmap seeded into the worker

1. Supervised engineering workload execution path
2. Safe local sandbox capability boundary
3. Deterministic calculation workloads and manifests
4. Simulation study and provenance primitives
5. Shadow-mode telemetry and verification reporting

These are starting points, not permanent commitments. The project should continue to replace assumptions with benchmarks and verified integrations.

## Why the original 10-second loop was changed

A 10-second delay would mean thousands of requests per day, which is incompatible with the currently listed free-plan daily request budget. The implementation therefore uses a request budget plus a long minimum interval and exponential backoff for HTTP 429 responses.

The worker also uses OpenRouter's API endpoint at `/api/v1/chat/completions` and structured JSON output, matching the current OpenRouter API surface.

## Important privacy note

Do not send private repositories, confidential engineering data, passwords, API keys, financial credentials, or other sensitive material to a free model unless the provider/model policy has been checked and the data is appropriate to send. OpenRouter exposes provider/model information and policy controls, but the policy can differ by provider/model.
