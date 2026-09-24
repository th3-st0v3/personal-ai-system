# PASI self-hosted GitHub Actions runner recovery

PASI authoritative CI uses the repository self-hosted runner labels:

- `self-hosted`
- `linux`
- `x64`
- `pasi-wsl`
- `pasi-desktop`
- `pasi-capabilities-v1`

The test/security jobs use the first four required labels, while runner capability maintenance also requires `pasi-desktop`. GitHub matches self-hosted labels cumulatively, so the runner must have every label requested by a job.

## Why the queue happens

A self-hosted job remains queued when GitHub cannot find an online and idle runner matching its labels. A single PASI runner can also make independent jobs execute serially; unlike separate GitHub-hosted workers, one machine cannot execute several runner jobs at once through a single runner listener.

A local runner can report `Connected to GitHub` and `Listening for Jobs` while GitHub CLI/UI briefly still reports queued metadata. Treat the runner journal as direct evidence of job assignment and use `gh run view` after the run completes for authoritative conclusions.

## Fast validation versus live acceptance

The authoritative `test` workflow has two modes:

- **fast** (the default for branch pushes): runs the existing Python unit/contract tests, JavaScript unit/fixture tests, shell syntax, and JSON validation through `scripts/check_fast.sh`.
- **live** (manual `workflow_dispatch` only): additionally runs the Chromium response-recovery and prompt-submission acceptance scripts against their local fixture/browser environment.

The fast path deliberately does not run `apt-get`, start a live Chromium acceptance session, invoke the full `check_all.sh` quality sweep, or duplicate individual test suites. Existing PASI tests already use `FakeTransport`, mocked adapters, temporary directories, local HTTP fixtures, and JSDOM fixtures to exercise browser/bridge behavior without requiring a real ChatGPT session.

The slower `scripts/check_all.sh` suite remains available for full local/maintenance validation. It performs broader quality checks such as static typing, Markdown linting, browser-use compatibility, web smoke tests, and the discovered test suite.

## Register or repair the WSL runner

On the WSL machine that is intended to execute PASI:

```bash
cd ~/workspace/personal-ai-system
export PASI_GITHUB_RUNNER_TOKEN='<fresh repository runner registration token>'
bash scripts/bootstrap_pasi_github_runner.sh
unset PASI_GITHUB_RUNNER_TOKEN
```

Generate the token from the repository's **Settings → Actions → Runners → New self-hosted runner** flow. GitHub states that repository runner registration tokens are time-limited; the current documentation says the token expires after one hour. Never commit the token or put it in a repository file.

The bootstrap script:

1. installs the latest Linux x64 runner package when `config.sh` / `run.sh` are absent;
2. registers a new runner with `pasi-wsl,pasi-desktop,pasi-capabilities-v1` when no local runner configuration exists;
3. leaves an already configured runner registration untouched by default;
4. uses `svc.sh` and systemd when WSL systemd is available;
5. otherwise leaves the runner ready for `./run.sh` and reports that systemd persistence still needs to be enabled.

## Repair a connected-but-unassigned registration

Use this path when all of the following are true:

- the runner service is active locally;
- the runner log says `Connected to GitHub` and `Listening for Jobs`;
- GitHub still shows queued jobs with `runner_id=0` / no runner name;
- a fresh runner registration token is available.

Run:

```bash
cd ~/workspace/personal-ai-system
export PASI_GITHUB_RUNNER_TOKEN='<fresh repository runner registration token>'
export PASI_GITHUB_RUNNER_FORCE_RECONFIGURE=1
bash scripts/bootstrap_pasi_github_runner.sh
unset PASI_GITHUB_RUNNER_FORCE_RECONFIGURE
unset PASI_GITHUB_RUNNER_TOKEN
```

Forced reconfiguration stops and removes the local systemd runner service, clears the local registration markers, and registers the same runner name again with the configured custom labels. The registration uses `--replace` so an existing repository runner with the same name can be replaced.

Do not enable forced reconfiguration as a permanent environment setting. It is an explicit recovery action because it interrupts the current runner service.

## Verify that the listener is actually running

From the runner directory:

```bash
cd ~/.pasi/actions-runner
sudo ./svc.sh status
```

A healthy runner should be connected to GitHub and listening for jobs. For a systemd-managed runner, inspect the service with:

```bash
systemctl --type=service | grep actions.runner
sudo journalctl -u '<runner-service-name>' -f
```

GitHub's runner documentation uses the `Listening for Jobs` state as the signal that the application is ready to accept work.

Then manually dispatch the authoritative test workflow or push a new commit to a branch. The job should show the PASI self-hosted runner rather than `ubuntu-latest`.

## Clear stale branch runs before diagnosing the current head

When one self-hosted runner has been offline, several older jobs may already be queued. They can make the machine execute old work before the newest head is reached.

List branch runs:

```bash
gh run list \
  -R th3-st0v3/personal-ai-system \
  --branch pasi/runner-recovery-20260922 \
  --limit 100
```

Cancel stale queued/in-progress runs before diagnosing a new head. Do not cancel the current run you intend to validate.

For repeated workflow updates, the repository's concurrency controls cancel stale validation heads, but jobs that were already assigned can still briefly finish or unwind on the runner.

## Authoritative billing boundary

PASI validation should not use a GitHub-hosted fallback. GitHub documents self-hosted runner usage as free of GitHub Actions usage charges, while private-repository jobs on GitHub-hosted standard runners consume included minutes and can be billed after the allowance is exhausted.

This is why authoritative PASI validation uses self-hosted labels instead of allowing queued infrastructure to silently turn into hosted validation attempts.

## Long-running WSL operation

For unattended PASI operation, prefer a systemd-managed runner service. GitHub documents `svc.sh install`, `svc.sh start`, and `svc.sh status` for Linux systems using systemd. The runner application itself must remain active to accept queued jobs.
