# PASI Overnight Automation

PASI can run a bounded unattended engineering loop for **8-12 hours**. The launcher now defaults to **12 hours**. The duration is a scheduler ceiling: useful progress still depends on the machine remaining powered, browser/controller availability, provider availability, and the ability to find verified work.

The runner uses an isolated Git worktree, persistent state, bounded retries, deterministic repository validation, and a dedicated Git branch. It does not write directly to `main`.

## Routing policy

Thinking/reasoning mode is required for **every** PASI task and remains independent of repository context.

The public PASI repository is the default repository context source:

- Repository: `https://github.com/th3-st0v3/personal-ai-system`
- Default branch: `https://github.com/th3-st0v3/personal-ai-system/tree/main`

PASI starts with public GitHub retrieval. In `--github auto` mode, when the model provides evidence that public repository retrieval is unavailable or insufficient, PASI automatically attaches the ChatGPT GitHub app and retries in the **same conversation**. This preserves conversational context while retaining the connector as a precision fallback. Explicit `--github fallback` and `--github always` remain available.

Thinking stays enabled when the GitHub app is used.

## Browser automation components

The native Chromium controller is the preferred path. During the transition, the existing PASI ChatGPT Controller Loader in Tampermonkey can remain enabled as a fallback. Keep the legacy direct controller disabled when the loader/native controller is installed.

The native Chromium controller talks only to the PASI bridge on `127.0.0.1:8765`. The bridge exposes bounded queue, health, state, response, cancellation, and observation endpoints; the browser controller does not grant PASI arbitrary OS access.

The controller update mechanism is evidence-gated. A model response cannot directly install a controller update; it can only request one through the validated PASI controller-update signal.

## Computer-use capability boundary

PASI exposes computer access through named capabilities rather than raw desktop control. The default local gateway can provide bounded system metadata, approved workspace listings/reads/searches, IDE state, and the explicitly gated resource-acquisition capability.

Credentials and secret material are never exposed through the computer-use gateway. Arbitrary command execution, arbitrary file writes, application launch, and unrestricted desktop control remain outside the unattended capability set.

### Preapproved resource acquisition

The unattended system can acquire a resource when the request matches a narrowly scoped local preapproval. Unapproved requests are **not** an approval pause. PASI writes an obstacle record and continues with other work.

The optional policy file is `.runtime/policy/preapprovals.json` or the path specified by `PASI_PREAPPROVALS_PATH`. It is local runtime configuration and should not be committed with credentials or other secrets.

The policy uses schema version 1. Example:

```json
{
  "schema_version": 1,
  "approvals": [
    {
      "id": "python-build-downloads",
      "action": "public_download",
      "hosts": ["example.com"],
      "max_bytes": 5000000,
      "expires_at": "2026-12-31T23:59:59Z"
    },
    {
      "id": "approved-test-package",
      "action": "package_install",
      "manager": "pip",
      "packages": ["requests==2.33.0"],
      "expires_at": "2026-12-31T23:59:59Z"
    }
  ]
}
```

Public downloads are HTTPS-only, bounded by the preapproved byte limit, placed in `.runtime/acquired`, and can require an expected SHA-256 digest. Python package acquisition requires an exact version pin and an exact package entry in the policy. Package installation is therefore an explicit, locally preapproved execution boundary rather than a general-purpose command runner.

## Obstacle handling

Every obstacle is designed to become **work state, not a stop state** when safe continuation is possible.

PASI records recoverable or externally blocked conditions in `.runtime/automation/obstacles.jsonl` and maintains `.runtime/automation/action-list.md`. Sensitive values in obstacle details are redacted and entries are size-bounded.

Typical obstacle records include stale browser/controller state, provider limits, authentication/security challenges, verification failures, failed task attempts, unavailable preapproved resources, and deferred retry backoffs.

A background authorization request that needs human approval is returned as deferred/denied without moving an unattended control session into an approval-waiting phase. Interactive sessions keep the ordinary approval workflow.

The scheduler can therefore continue with fallback providers, another task, another research source, or a recovery task. Human-required items remain visible in the action list for later resolution.

## Automation continuation

The overnight supervisor starts in an **automation** phase. Its initial tasks improve controller reliability, state continuity, browser recovery, provider fallback, task continuation, and reduction of repeated human input.

After two verified automation tasks, the supervisor normally evaluates whether to enter Engineering OS work. A task can explicitly emit:

`PASI_AUTOMATION_CONTINUE: true`

when its evidence or research establishes that another automation/computer-use/recovery/integration/security capability is materially necessary to satisfy the current objective. That signal keeps the automation phase active for another verified task. It is not intended for optional polish.

The scheduler never treats “approval is required” as a reason to sit idle. When an action cannot be performed safely under the active preapproval/authorization policy, it is recorded and the runner continues where it can.

## One-command overnight run

The detached launcher defaults to 12 hours:

```bash
cd ~/workspace/personal-ai-system
bash scripts/start_pasi_overnight.sh
```

Choose another duration inside the supported range when needed:

```bash
PASI_OVERNIGHT_HOURS=8 bash scripts/start_pasi_overnight.sh
```

or:

```bash
PASI_OVERNIGHT_HOURS=12 bash scripts/start_pasi_overnight.sh
```

The launcher prints the runner log, persistent state file, and action-list paths. Structured events are stored in `.runtime/overnight/events.jsonl`.

## First-time local verification

From WSL:

```bash
cd ~/workspace/personal-ai-system
git checkout main
git pull --ff-only
source .venv/bin/activate
# Legacy Tampermonkey distribution is no longer required for native runs.
```

In another WSL terminal:

```bash
curl -fsS http://127.0.0.1:8765/health
curl -fsS http://127.0.0.1:8765/health
```

Refresh `https://chatgpt.com/`. The browser console should show the native controller or PASI loader starting successfully.

The unattended runner starts the PASI bridge and controller-distribution service automatically. The manual server command is primarily for first-time validation and troubleshooting.

## Provider and browser recovery

A conversation-context limit is treated differently from an account/model/provider usage limit.

When the current conversation itself is exhausted, PASI creates one replacement conversation and retries the current task once. It does **not** treat opening another conversation as a way to bypass account/model usage restrictions.

Provider usage limits, authentication challenges, stale browser state, and other transient provider failures are routed through bounded fallback/recovery logic. The final overnight hardening wrapper deliberately converts long retry backoffs into immediate continuation and uses configured fallback providers when possible.

The runner cannot recover an interactive security challenge without a user eventually completing that challenge, but it no longer needs to make that the reason for idling the entire automation run.

## Monitoring and stop

```bash
bash scripts/status_pasi_overnight.sh
```

Request a graceful stop:

```bash
bash scripts/stop_pasi_overnight.sh
```

The most useful unattended diagnostics are:

```text
.runtime/overnight/state.json
.runtime/overnight/events.jsonl
.runtime/automation/obstacles.jsonl
.runtime/automation/action-list.md
```

## Resume after interruption

Successful task commits already made to the dedicated overnight branch remain intact. Resume with:

```bash
cd ~/workspace/personal-ai-system
bash scripts/pasi_overnight.py --resume
```

Interrupted uncommitted task changes in the dedicated overnight worktree are cleaned before resume. Runtime state is schema-validated so stale incompatible state cannot silently alter the safety model.

## Verification and completion

A task is not accepted from model prose alone. The response must provide the PASI completion markers and a unified patch. PASI then checks patch paths, forbids symlink/submodule additions, applies the patch, runs `scripts/check_all.sh`, confirms that changes remain, and commits the verified result to the dedicated branch.

A task that fails deterministic verification receives bounded repair attempts. When those attempts are exhausted, PASI records the failure and advances to a different task/recovery path instead of repeating forever.

## Safety boundary

The overnight runner does not automatically merge into `main`, publish releases, expose credentials, perform autonomous financial execution, or grant the AI arbitrary OS-wide command/desktop control.

Preapproval is capability-specific and should be narrow, time-bounded, and explicit. Unapproved actions are recorded for later human review rather than silently broadened into permission.

Windows/WSL must remain powered and available for the selected duration. No local automation architecture can continue operating on a machine that is fully powered off or suspended.
