# PASI 12-Hour Automation Run

This is the supported WSL launch path for a long unattended engineering run. The runner uses a dedicated worktree, persistent state, bounded task retries, deterministic verification, provider fallback, dynamic setup discovery, web-evidence injection, and browser recovery. It is designed to make substantial repository progress without turning external web content or provider output into unrestricted execution authority.

## One-time browser preparation

Use one Chromium/Chrome profile dedicated to PASI. Open `https://chatgpt.com/` and sign in manually. Complete any CAPTCHA, Cloudflare, MFA, security check, or other interactive verification yourself. Keep the browser profile/session available while PASI runs.

Install **one** PASI browser-controller path:

- Preferred: load the unpacked native extension from `automation/chromium/pasi-chatgpt` in Chromium/Chrome.
- Alternative: install `automation/tampermonkey/chatgpt-controller-loader.user.js` in Tampermonkey. Do not run a second directly-installed PASI ChatGPT controller at the same time.

The GitHub account/app is only needed when account-scoped GitHub access or the connected ChatGPT GitHub fallback is required. The public PASI repository is the default repository context.

## Start from WSL

```bash
cd ~/workspace/personal-ai-system
source .venv/bin/activate
bash scripts/start_pasi_12h.sh
```

That single command performs the setup preflight and starts the supported 12-hour runner in the background. The launcher now routes through `scripts/pasi_automation_entrypoint.py`, which enforces the 25-minute response budget, captures new setup requirements, optionally injects explicitly supplied web research, and records verified self-improvement surfaces.

To supply specific public web pages as research context without editing the repository prompt, set a bounded comma-separated list first:

```bash
export PASI_WEB_CONTEXT_URLS="https://example.com/docs,https://example.org/spec"
bash scripts/start_pasi_12h.sh
```

Web pages are retrieved as **untrusted research data**. Page text can contain prompt injection or misleading instructions; PASI must not treat that text as authorization to execute commands, reveal secrets, or bypass controls.

## Monitor progress

In a second WSL terminal:

```bash
cd ~/workspace/personal-ai-system
bash scripts/status_pasi_overnight.sh
tail -f .runtime/overnight/runner.log
```

The generated setup checklist is available at:

```bash
cat .runtime/automation/setup-requirements.md
cat .runtime/automation/setup-requirements.json
```

The setup catalog covers both machine-side resources and websites that need an authenticated browser session. When the agent discovers a genuinely necessary download or interactive-login prerequisite, it adds a bounded metadata entry automatically. PASI does not store passwords, cookies, session tokens, or API keys, and acquisition remains subject to explicit preapproval.

## What the long-running loop can improve

Each task is sent through the existing completion contract and deterministic patch verification. The task prompt explicitly encourages improvements to the WSL/scripts, VS Code integration, Chromium/Tampermonkey controller, research/evidence handling, and recovery layers when a verified gap materially affects unattended reliability. A successful task is only accepted after the configured repository validation suite passes and the resulting change is committed to the dedicated automation branch.

Browser-controller changes are therefore developed and verified as part of the automation run, but active controller publication still uses the repository's signed/hashed release path rather than silently executing unreviewed browser code. This keeps self-improvement connected to the live system without removing the release boundary.

## Recovery behavior

PASI uses a hard 25-minute generation ceiling for an individual ChatGPT response. When a task appears stuck, the browser recovery companion uses this sequence:

1. Check whether a completed response is already visible and preserve it instead of duplicating work.
2. Detect connection-loss/security-state signals and record them separately.
3. Reload the active ChatGPT page once when the 25-minute response window is exhausted or a clear connection failure is visible.
4. Allow a bounded post-reload grace period for the page/controller to settle.
5. If the response still cannot be recovered, create a verified fresh chat and mark the original operation `CHAT_RECOVERED_RETRY` so the supervisor retries the **same task** rather than starting a duplicate task.
6. Authentication, CAPTCHA, Cloudflare, MFA, and other security challenges are recorded as human-intervention obstacles. PASI never attempts to bypass them.

The native background watchdog remains responsible for shorter-lived stale-tab recovery; the response recovery companion handles the longer-lived, operation-specific failure mode.

## Stop

```bash
cd ~/workspace/personal-ai-system
bash scripts/stop_pasi_overnight.sh
```

## Inspect the setup catalog

```bash
cd ~/workspace/personal-ai-system
.venv/bin/python scripts/pasi_setup.py
```

Use `--json` for machine-readable output:

```bash
.venv/bin/python scripts/pasi_setup.py --json
```
