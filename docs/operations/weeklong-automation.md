# PASI One-Week Automation Run

This is the extended WSL launch path for a 168-hour unattended engineering run. The 12-hour launcher remains available as a bounded stress-test convenience, but the underlying automation is not conceptually limited to 12 hours.

## Start

From WSL:

```bash
cd ~/workspace/personal-ai-system
source .venv/bin/activate
bash scripts/start_pasi_168h.sh
```

The launcher performs the setup preflight, prevents duplicate starts, detaches the runner from the terminal, and writes persistent runtime state and logs under `.runtime/overnight/`.

The extended runtime entrypoint removes only the old artificial 12-hour parser ceiling. The existing minimum-duration safety bound and all task, patch, verification, provider, browser, and human-approval boundaries remain in force.

## Monitor

Use the following checks from a second WSL terminal:

```bash
cd ~/workspace/personal-ai-system
bash scripts/check_pasi_weekly_run.sh
```

For the live log:

```bash
tail -f .runtime/overnight/runner.log
```

For the standard supervisor view:

```bash
bash scripts/status_pasi_overnight.sh
```

Useful persisted files:

```bash
cat .runtime/overnight/state.json
 tail -n 50 .runtime/overnight/events.jsonl
cat .runtime/automation/action-list.md
cat .runtime/automation/setup-requirements.md
```

The state file contains the current phase, task, counters, deadline, branch, and last result. The event log provides a durable execution trail. The setup catalog records discovered machine and interactive-login requirements without storing passwords, cookies, session tokens, or API keys.

## Recovery

The runner has persistent state, bounded retries, browser/provider recovery, and a PID-based duplicate-run guard. If the process is dead before the stored deadline, the normal recovery command is:

```bash
cd ~/workspace/personal-ai-system
bash scripts/start_pasi_168h.sh --resume
```

That launcher removes a stale PID file when necessary. `--resume` reuses the persisted run when its existing deadline is still active; when that deadline has already passed, the engine starts a new 168-hour run instead of pretending the expired run is still active.

When a provider, browser session, CAPTCHA, Cloudflare challenge, MFA prompt, or other authentication state requires human intervention, the system records the obstacle rather than attempting to bypass the security control.

## Stop

```bash
cd ~/workspace/personal-ai-system
bash scripts/stop_pasi_overnight.sh
```

## Operational expectation

A 168-hour deadline means the runner is configured to operate for seven days. It is not a guarantee that external systems cannot fail for seven days. Unrecoverable local failures, unavailable authentication, network outages, or other hard prerequisites can still terminate a run. The purpose of the extended launcher is to remove the artificial 12-hour software ceiling while retaining the existing recovery and verification boundaries.

## Autonomous promotion

The 168-hour runner promotes only after a task has passed repository validation and produced a Git commit. Promotion is risk-gated:

- Standard-risk changes may open a PR and request GitHub auto-merge only after all reported checks pass.
- Controller, browser, bridge, recovery, provider-routing, workflow, startup, timeout, sandbox, promotion, and governance changes remain in normal human-review PRs.
- A previously closed PR is never reopened and no replacement PR is created solely to revive that closed work.
- Auto-merge uses squash merge and asks GitHub to delete the merged work branch.

This is repository promotion, not direct unattended modification of main: GitHub remains the merge authority, required checks must pass, and protected/control-plane changes remain review-gated.
