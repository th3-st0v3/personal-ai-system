# PASI Quality Proofing Workflow

PASI uses a progressive quality-proofing model that stays on the self-hosted `pasi-wsl` runner for repository validation. The developer hooks provide the fast PR/local layer; the separate quality workflow runs its extended coverage/post-merge checks on `main`/`beta-foundation` and on schedule, keeping the single WSL runner from accumulating duplicate PR jobs.

## Stage 1 — Local proofing

Developers can install the repository's local hooks with:

```bash
python -m pip install -r requirements-dev.txt
pre-commit install
```

The hooks run:

- `scripts/pasi_local_proof.py --staged` for Python, JavaScript, shell, and JSON syntax/data validation.
- Fast PASI contract tests covering the runner/billing contract, self-hosted runner preflight, controller-distribution retirement, and quality-workflow composition.

For a full-tree local proofing pass:

```bash
python scripts/pasi_local_proof.py --all
```

This layer is deliberately based on repository-local commands rather than remote hook repositories.

## Stage 2 — Continuous integration

The existing `test` workflow is the authoritative functional CI gate. It covers deterministic validation, Python tests, JavaScript tests, browser fixtures, integration checks, type validation, smoke tests, and PASI runtime contracts.

The workflow begins with runner preflight and defaults to `pasi-wsl`. Its manual `runner_mode` input can explicitly select `github-hosted` later when GitHub-hosted usage restrictions have been cleared.

## Stage 3 — Review and static/security analysis

Pull requests provide the human review boundary. After successful test validation, the existing security workflow performs CodeQL analysis, repository secret scanning, and dependency auditing on the self-hosted runner.

PASI also retains the agent-impact and self-modification-boundary audits as observational review evidence.

## Stage 4 — Post-merge quality gate

The new `pasi-quality-proofing.yml` workflow measures Python branch coverage on `main`, `beta-foundation`, scheduled runs, or an explicit manual request and archives the report as an Actions artifact.

On a push to `main`, the post-merge job runs the existing `scripts/ci_web_smoke.py` after coverage succeeds.

PASI does not currently have a separate deployable staging environment or customer UAT target. The post-merge smoke gate therefore validates the real repository web/API surface on the same controlled self-hosted substrate instead of creating a fake staging deployment.

## Coverage policy

Coverage is currently evidence-producing rather than threshold-enforcing. The workflow records branch coverage without inventing a minimum percentage before a baseline has been established. A future change can introduce a `--fail-under` threshold once the repository has a measured baseline and an intentional policy.

## No duplicate security pipeline

The quality workflow intentionally does not duplicate CodeQL, secret scanning, or dependency auditing because those controls already exist in `.github/workflows/pasi-security-analysis.yml`. This keeps one authoritative implementation for each security control.

## Runner and cost boundary

All jobs in the quality-proofing workflow use:

```
[self-hosted, linux, x64, pasi-wsl]
```

The workflow contains no GitHub-hosted runner selector. GitHub-hosted execution remains an explicit operator choice only in the primary `test.yml` workflow through its `runner_mode` input.
