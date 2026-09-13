# OpenRouter Build Assistant

This stage adds a supervised, resumable engineering build assistant. It uses OpenRouter's free-model router by default, keeps progress in a local JSON checkpoint, handles rate limits, and places model-generated changes in an approval queue instead of writing them directly into the repository.

OpenRouter currently lists `openrouter/free` as a zero-price router for available free models. Its current free plan lists 50 requests/day and 20 requests/minute; limits can change, so check the current pricing page before changing the worker budget.

## What this does

Think of it as a second AI helper for the project. It can read a bounded snapshot of the repository, inspect the engineering roadmap, ask the model for the next single improvement, and remember the result.

It does **not** silently edit your code, run arbitrary shell commands, deploy software, trade, move money, or access credentials.

The loop is:

```text
read project snapshot
        ↓
AI proposes one change
        ↓
validate proposal
        ↓
save to approval queue
        ↓
human review / apply
        ↓
run tests
        ↓
record result
        ↓
next cycle
```

## Easiest setup

1. Create one OpenRouter API key in your OpenRouter account.
2. In the WSL terminal for this project, set it temporarily:

```bash
export OPENROUTER_API_KEY='paste-your-key-here'
```

Do not put the key into Python source code, Git, screenshots, or committed configuration.

3. Run one safe cycle:

```bash
cd ~/workspace/personal-ai-system
PYTHONPATH=src python scripts/openrouter_build_loop.py --once
```

4. View the saved proposal:

```bash
python -m json.tool .runtime/ai_os_project_state.json
```

Look under `approval_queue`. Nothing is applied automatically.

## Continuous mode

```bash
PYTHONPATH=src python scripts/openrouter_build_loop.py
```

The worker uses a conservative daily budget and pacing. When the budget is reached, it exits cleanly and preserves state for the next run.

## Model selection

The default is:

```text
openrouter/free
```

This router dynamically selects from the current free-model pool and filters for supported capabilities such as structured output and tool calling. A specific compatible free model can be selected with `--model` when you need reproducible model choice.

## Do not bypass provider limits

Do **not** create multiple accounts or rotate credentials to defeat provider rate limits. OpenRouter's current terms prohibit creating multiple accounts for the purpose of circumventing use limits.

A legitimate future multi-provider architecture is different: each provider can be integrated through its own documented API and its own account/quota, with the runtime enforcing each provider's stated limits rather than bypassing them.

## Privacy

The repository snapshot is intentionally bounded and excludes common credential/runtime locations. Still, review what the worker sends before using it with private engineering material. Free endpoints may have provider-specific data policies, so sensitive or proprietary material should only be sent when the applicable model/provider policy has been checked.

## Long-running use

For a free account, the current listed budget is 50 requests/day, so a 10-second loop is not an appropriate strategy. The worker therefore uses a request budget, minimum interval, and exponential backoff for 429/network failures.

The project should optimize **useful engineering progress per request**, not maximize request count.
