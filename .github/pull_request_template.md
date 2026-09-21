# Pull Request Scope

## Primary subsystem

<!-- Choose one primary owner. Cross-subsystem changes require justification below. -->

- [ ] Chromium / ChatGPT browser automation
- [ ] Bridge / controller transport
- [ ] Overnight runner / recovery / task lifecycle
- [ ] Operations / startup / service management
- [ ] Legacy / compatibility
- [ ] Application / backend
- [ ] Tests / CI / developer tooling
- [ ] Documentation

**Primary subsystem:** 

**Single engineering objective:** 

## Scope

### Intended files/modules

<!-- List the files or modules that should change. -->

- 

### Scope justification

<!-- Explain why every touched subsystem/file is required. For >15 files, >500 lines, >2 subsystems, or control-plane changes, provide a file-by-file justification. -->

| Path / module | Why it is required | Primary owner / dependency |
| --- | --- | --- |
| file/path | reason | owner or dependency |

### Cross-subsystem exception

- [ ] No cross-subsystem exception.
- [ ] Direct dependency: splitting this change would leave the primary change incomplete or incorrect.
- [ ] Coherent migration: the boundary cannot be split safely without duplicating or invalidating an interface.

**Exception justification:** 

## Dependencies

**Prerequisite PRs / commits / runtime conditions:**

- 

**Existing work intentionally reused instead of copied:**

- 

## Tests

**Exact commands/checks run:**

```text
# command(s)
```

**Environment-dependent checks not run and why:**

- 

## Rollback

**Smallest safe rollback/checkpoint:**

- 

## Risk

**Important failure modes:**

- 

**Evidence that detects those failures:**

- 

## Protected boundaries

- [ ] I did not weaken tests or validators to make this PR pass.
- [ ] I did not modify protected governance/security/promotion controls unless explicitly scoped for review.
- [ ] I did not include unrelated Chromium, bridge, overnight, ops, or legacy work.
- [ ] I checked for duplicate/redundant work already present on `main`.

## Merge readiness

- [ ] Scope is one coherent engineering objective.
- [ ] Required tests are green or documented as environment-dependent.
- [ ] Dependencies are satisfied.
- [ ] Rollback is defined.
- [ ] Large/cross-cutting scope is explicitly justified.
