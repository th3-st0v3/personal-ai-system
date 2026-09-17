# PASI Overnight Automation

PASI can run a bounded unattended engineering loop for 8-12 hours. The selected duration is a scheduler ceiling, not a guarantee of 8-12 hours of useful ChatGPT work: the effective unattended runtime is limited by the selected deadline, ChatGPT/provider availability, conversation context limits, browser/controller availability, authentication/security challenges, and Windows/WSL power availability.

The runner uses an isolated Git worktree, persistent state, bounded retries, repository validation, and a dedicated Git branch so it does not write directly to `main`.

## Routing policy

Thinking/reasoning mode is required for **every** PASI task and remains independent of repository context.

The public PASI repository is the default repository context source:

- Repository: `https://github.com/th3-st0v3/personal-ai-system`
- Default branch: `https://github.com/th3-st0v3/personal-ai-system/tree/main`

The ChatGPT GitHub app is never attached merely because a task mentions GitHub, a repository, code, a branch, or a file. It is an explicit fallback only when the caller selects `--github fallback`.

## Browser automation components

Keep the recovered legacy direct ChatGPT controller installed but **disabled**. Keep the current `Personal AI System - ChatGPT Controller Loader` enabled. Also install the `Personal AI System - ChatGPT Runtime Watchdog` userscript from `automation/tampermonkey/chatgpt-runtime-watchdog.user.js` and leave it enabled while unattended automation is running.

The loader reads the verified controller release from the local PASI controller-distribution service on `127.0.0.1:8766`, verifies the controller against the Git blob identity, and activates it inside Tampermonkey. The loader polls the local service every 30 seconds.

The runtime watchdog is read-only browser telemetry. It does not click controls or submit messages. It samples the ChatGPT page every five seconds and reports provider/account/model usage-limit markers, authentication/security challenges, conversation-context exhaustion, Thinking-state observations, page visibility, and composer readiness to the local bridge.

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

Refresh `https://chatgpt.com/`. The browser console should show the loader/controller and runtime watchdog starting successfully.

The unattended runner starts the local PASI bridge and controller-distribution service automatically. The manual server command is mainly useful for first-time validation and troubleshooting.

## Chat limitations and recovery

PASI distinguishes a **conversation context limit** from a **provider/account/model usage limit**.

A conversation-context limit is recoverable: `scripts/pasi_chat.py` creates one replacement conversation and retries the task once. Opening another conversation is intentionally not treated as a way to bypass account/model usage limits.

Provider-wide or account/model usage limits are an external runtime ceiling. `scripts/pasi_chat_guard.py` monitors browser observations while a task runs. When it detects a provider usage limit it returns a dedicated exit status to the overnight supervisor. The supervisor performs only bounded backoff attempts and then stops with a human-required state rather than repeatedly opening chats that cannot reset the limit.

Authentication and security challenges also stop unattended execution because they require interactive human intervention.

Transient controller/browser failures receive bounded retries and backoff. A task that repeatedly fails the completion contract or deterministic verification is not allowed to loop forever; it transitions to a recovery task and records the failure evidence.

## Automation-first phase gate

The overnight supervisor starts in an **automation** phase. Its first work is to improve PASI itself: controller reliability, state continuity, response detection, provider-limit handling, recovery, and reduction of repeated human input.

After two completed automation tasks, PASI runs an evidence gate. The gate must explicitly report one of these consistent states:

- `proceed_engineering` + `none`: no concrete, useful automation improvement remains, so PASI may enter the Engineering OS phase.
- `continue_automation` + `concrete`: a concrete automation improvement remains, so PASI stays in the automation phase and works on another automation task before the next gate.

The gate must include evidence. Contradictory or missing gate markers are rejected. This prevents PASI from switching to ordinary Engineering OS work just because the automation backlog is inconvenient; the transition is tied to a documented diminishing-returns decision.

Once the gate allows the transition, PASI enters the **Engineering OS** phase and works through engineering tasks such as verification, task planning, UX/state visibility, and provider-neutral control-plane improvements. A user-supplied `--task` becomes the first Engineering OS task after a successful transition.

## One-command overnight run

The detached launcher defaults to 10 hours, which is inside the supported 8-12 hour range:

```bash
cd ~/workspace/personal-ai-system
bash scripts/start_pasi_overnight.sh
```

The process is detached from the terminal. Logs are written to `.runtime/overnight/runner.log`; structured events are in `.runtime/overnight/events.jsonl`; persistent run state is in `.runtime/overnight/state.json`.

To choose a duration explicitly:

```bash
PASI_OVERNIGHT_HOURS=12 bash scripts/start_pasi_overnight.sh
```

To reserve a specific Engineering OS task for after the automation gate:

```bash
bash scripts/start_pasi_overnight.sh --task "Improve the Engineering OS task planner using verified repository gaps and reproducible evidence."
```

The overnight runner uses the public repository as its normal context source and keeps Thinking enabled on every task. The GitHub app is not automatically added by repository detection.

## Monitor and stop

Check the current phase, task, counters, deadline, provider-limit pauses, branch, and local service health:

```bash
bash scripts/status_pasi_overnight.sh
```

Request a graceful stop:

```bash
bash scripts/stop_pasi_overnight.sh
```

## Resume after an interruption

When the runner is interrupted, successful task commits already made to its dedicated branch remain intact. Start it again with:

```bash
cd ~/workspace/personal-ai-system
bash scripts/pasi_overnight.py --resume
```

The supervisor restores only schema-v2 state. An older v1 state file is treated as non-resumable so stale runtime semantics cannot silently bypass the automation phase gate.

## Task completion and continuation

A task is not accepted as complete from model prose alone. The implementation response must provide the explicit completion-contract markers, a unified patch, and evidence. PASI then applies the patch only after path checks, rejects symlink/submodule additions, runs `scripts/check_all.sh`, confirms that repository changes remain, commits the verified result, and optionally pushes the dedicated branch.

After a verified completion, the next task comes from the model's explicit `PASI_RESULT_NEXT_TASK` marker when it is new. Otherwise PASI chooses a deterministic non-repeating backlog item. A task that fails its completion contract or verification receives bounded repair attempts; after the retry budget is exhausted, PASI creates a recovery task instead of repeating the same failed approach indefinitely.

## Safety boundary

The overnight runner changes only the isolated repository worktree and its dedicated Git branch. It does not automatically merge into `main`, publish a release, execute arbitrary model-provided shell commands as the change mechanism, or grant the ChatGPT GitHub app repository write access.

Browser automation remains scoped to the ChatGPT controller. The runtime watchdog is telemetry-only; it does not alter the page. The browser automation does not require OS-wide mouse or keyboard takeover, so the user can continue using other applications normally. The ChatGPT controller should not be used in the same browser tab for unrelated manual ChatGPT work while a queued PASI operation is actively running.

For true unattended operation, Windows/WSL must remain powered and available for the full selected duration. The PASI runner cannot continue through a powered-off machine or a fully suspended WSL environment.
