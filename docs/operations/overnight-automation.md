# PASI Overnight Automation

PASI can run a bounded unattended engineering loop for 8-12 hours. The runner uses an isolated Git worktree, persistent state, bounded retries, repository validation, and a dedicated branch so it does not write directly to `main`.

## Browser controller setup

Keep the recovered legacy ChatGPT controller installed but **disabled**. Install only the current `Personal AI System - ChatGPT Controller Loader` userscript.

The loader is private-repository aware. It reads the controller release from the local PASI controller-distribution service on `127.0.0.1:8766`, verifies the controller against the Git blob SHA in `automation/tampermonkey/controller-sync.json`, and then activates the controller. The loader polls the local service every 30 seconds.

The loader intentionally uses `eval(source)` after verification because the controller must execute inside the Tampermonkey userscript environment. A Tampermonkey `no-eval` warning is therefore expected.

## One-time local verification

From WSL:

```bash
cd ~/workspace/personal-ai-system
git checkout main
git pull --ff-only
source .venv/bin/activate
python scripts/pasi_controller_server.py
```

In another WSL terminal:

```bash
curl -fsS http://127.0.0.1:8766/health
curl -fsS http://127.0.0.1:8765/health
```

Refresh `https://chatgpt.com/` after the controller-distribution service is up. The browser console should report that the loader activated and verified controller v2.4.3.

The `scripts/pasi_overnight.py` runner starts the controller-distribution service automatically, so this manual server command is mainly useful for troubleshooting and first-time validation.

## Launch an overnight run

The detached launcher defaults to 10 hours, which is inside the supported 8-12 hour range:

```bash
cd ~/workspace/personal-ai-system
./scripts/start_pasi_overnight.sh
```

The process is detached from the terminal. Logs are written to `.runtime/overnight/runner.log`; structured events are in `.runtime/overnight/events.jsonl`; persistent run state is in `.runtime/overnight/state.json`.

To choose a duration explicitly:

```bash
PASI_OVERNIGHT_HOURS=12 ./scripts/start_pasi_overnight.sh
```

To start with a different initial task:

```bash
./scripts/start_pasi_overnight.sh --task "Optimize the PASI computer-use control plane for lower human-input requirements while preserving safe approval boundaries."
```

## Monitor and stop

Check the current task, counters, deadline, branch, and local service health:

```bash
./scripts/status_pasi_overnight.sh
```

Request a graceful stop:

```bash
./scripts/stop_pasi_overnight.sh
```

## Resume after an interruption

When the runner is interrupted, successful task commits already made to its dedicated branch remain intact. Start it again with:

```bash
cd ~/workspace/personal-ai-system
./scripts/pasi_overnight.py --resume
```

The runner restores the persisted task/deadline state and discards only uncommitted changes in the dedicated overnight worktree before retrying the current task.

## Task completion and continuation

A task is not accepted as complete from model prose alone. The implementation response must provide the explicit completion contract markers, a unified patch, and evidence. PASI then applies the patch only after path checks, rejects symlink/submodule additions, runs `scripts/check_all.sh`, confirms that repository changes remain, commits the verified result, and optionally pushes the dedicated branch.

After a verified completion, the next task comes from the model's explicit `PASI_RESULT_NEXT_TASK` marker when it is new. Otherwise PASI chooses a deterministic non-repeating backlog item. A task that fails its completion contract or verification receives bounded repair attempts; after the retry budget is exhausted, PASI creates a recovery task instead of repeating the same failed approach indefinitely.

## Safety boundary

The overnight runner changes only the isolated repository worktree and its dedicated Git branch. It does not automatically merge into `main`, publish a release, execute arbitrary model-provided shell commands as the change mechanism, or grant the ChatGPT GitHub app repository write access.

Browser automation remains scoped to the ChatGPT controller. It does not require OS-wide mouse or keyboard takeover, so the user can continue using other applications normally. The ChatGPT controller should not be used in the same browser tab for unrelated manual ChatGPT work while a queued PASI operation is actively running.

For true unattended operation, Windows/WSL must remain powered and available for the full selected duration. The PASI runner cannot continue through a powered-off machine or a fully suspended WSL environment.
