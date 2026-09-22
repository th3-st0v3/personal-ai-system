# PASI self-hosted runner

The supported long-running topology keeps the Windows browser and Linux execution substrate separate:

```text
GitHub Actions
  ├─ self-hosted CI / security checks (pasi-wsl)
  └─ self-hosted live automation (pasi-desktop)
       └─ WSL Ubuntu
            ├─ PASI supervisor + engine
            ├─ authenticated localhost bridge :8765
            ├─ Git / Python / Node
            └─ optional Ollama
                    ↓
                 Opera GX
                    ↓
              native PASI extension
                    ↓
                 ChatGPT
```

VS Code is a development/debugging client. It is not a runtime dependency for unattended execution. WSL is the local Linux execution substrate for the bridge, runner, Git worktrees, validation sandbox, and optional local provider.

## One-time runner setup

From an authenticated WSL shell, the repository can bootstrap the runner without manually copying the registration token:

```bash
gh auth login
gh auth setup-git
bash scripts/install_pasi_self_hosted_runner.sh
```

The installer requests the short-lived repository registration token through the GitHub API when `gh` is authenticated, registers one Linux/x64 runner with `pasi-desktop,pasi-wsl,pasi-capabilities-v1`, and attempts to install the runner as a persistent service. The token is not stored by the script. GitHub's registration token expires after one hour. citeturn256204search0turn256204search5
In GitHub repository settings, open **Actions → Runners → New self-hosted runner** and select the Linux/x64 instructions GitHub provides for the current runner release. Install the runner inside WSL and assign the label `pasi-desktop`; `pasi-wsl` and `pasi-capabilities-v1` are recommended labels after the first capability reconciliation.

Do not store runner registration tokens in the repository. Use the short-lived token displayed by GitHub during runner setup.

Validate the machine with:

```bash
python3 scripts/reconcile_runner_capabilities.py --json
python3 scripts/pasi_desktop_preflight.py
```

To reconcile allowlisted dependencies and the optional local model:

```bash
python3 scripts/reconcile_runner_capabilities.py --apply --apply-optional --json
```

The same operation is exposed by the `pasi-runner-capabilities` GitHub workflow. It writes an atomic capability report at `~/.pasi/runner/capabilities.json` and uploads sanitized evidence. The runner state/control files follow `PASI_RUNTIME_DIR` when set; the default runtime directory is `~/.pasi/overnight`.

## CI runner fallback and readiness check

The repository test workflow selects the self-hosted `pasi-wsl` runner by default for pull requests, pushes, scheduled runs, and manual runs. Before the test jobs start, a runner preflight verifies that the job is actually executing on the expected self-hosted Linux/x64 environment.

For a local readiness check:

```bash
python scripts/check_pasi_self_hosted_runner.py
```

A manual `workflow_dispatch` exposes `runner_mode` with two choices:

- `self-hosted` — normal/default path; keeps validation independent of GitHub-hosted usage limits and payment state.
- `github-hosted` — explicit fallback/switch for use after GitHub-hosted Actions limits or payment restrictions have been cleared.

The workflow does not automatically fall back to GitHub-hosted runners. That prevents an offline or unhealthy self-hosted runner from silently recreating the billing-gated failure mode.

## Automation operation

The 168-hour launcher remains the process owner:

```bash
bash scripts/start_pasi_168h.sh --roadmap roadmaps/pasi-default.json
bash scripts/status_pasi_overnight.sh
```

The GitHub development workflow runs repository verification on the self-hosted WSL runner and performs live automation on the self-hosted desktop runner. The workflow itself is intentionally short-lived; the supervised PASI process owns the 168-hour boundary and durable state.

For the GitHub-native coding entry point, open a normal issue and comment exactly:

```text
/pasi run
```

The `pasi-autocode` workflow accepts that command only from repository collaborators, rejects pull-request conversations, creates an isolated `pasi/autocode/<run-id>` branch, validates the selected roadmap, and hands the run to the durable systemd service. A manual `workflow_dispatch` can select a different base ref or repository-relative roadmap. PASI then owns task selection, ChatGPT execution, verification, PR promotion, and continuation.

The Control Center reads capability and runner-state telemetry through the authenticated bridge. `Retry current` creates a task-bound control request, and `Panic stop` signals only a PID whose `/proc` command line identifies the PASI engine or supervisor. There is no arbitrary command endpoint.

## Capability contract

The desired environment is versioned in `config/runner/capabilities.json`. The reconciler can install only declared Debian packages, install repository Python requirements, and optionally pull the configured Ollama model. It does not accept arbitrary package names or arbitrary shell commands from model output.

GitHub runner labels are routing metadata, not proof that the machine currently satisfies the capability contract. The workflow performs the actual check before automation.

## Security boundary

Treat the self-hosted runner as trusted execution infrastructure. Do not route untrusted public pull requests into the `pasi-desktop` runner. Keep the native extension limited to its declared host permissions and keep bridge commands authenticated and allowlisted. The `/pasi run` issue-comment trigger requires an OWNER, MEMBER, or COLLABORATOR association.

## Recovery artifacts

Durable runner state is stored under `~/.pasi/overnight/`, including `state.json`, `handoff.json`, `events.jsonl`, `runner.pid`, and the task ledger. These files are the resume/diagnostic source of truth; VS Code is not a state store.
