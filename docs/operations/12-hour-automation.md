# PASI 12-Hour Automation Run

This is the supported WSL launch path for a long unattended engineering run. The runner uses a dedicated worktree, persistent state, bounded task retries, deterministic verification, and provider fallback. It does not bypass CAPTCHA, Cloudflare, MFA, or other security challenges.

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

The launcher performs a local prerequisite preflight, then starts the existing 12-hour supervisor in the background. The existing launcher writes the runner log and persistent state under `.runtime/overnight`. 

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

The checklist is expanded dynamically whenever a verified task response says a genuinely needed tool/download or authenticated website is required. Those entries are setup metadata only; acquisition remains subject to PASI's existing explicit preapproval policy.

## Recovery behavior

PASI uses a 25-minute generation ceiling for ChatGPT tasks. Before that hard ceiling, the browser recovery companion watches for a stalled response or a broken connection. Its recovery sequence is:

1. Detect the active ChatGPT operation and preserve a newly completed response when the page exposes one.
2. When recovery is needed, reload the current ChatGPT page once.
3. After reload, preserve a newly available response when possible.
4. Otherwise prepare a verified fresh ChatGPT conversation and mark the original operation for the overnight supervisor to retry as the **same task**, preventing duplicate task execution.
5. If a login/CAPTCHA/Cloudflare/MFA/security challenge is detected, PASI records the obstacle and does not attempt to bypass it.

The supervisor allows a bounded recovery grace period after the 25-minute generation ceiling so the browser can reload and settle before the task is considered failed.

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
