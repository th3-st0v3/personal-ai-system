# Pull Request Scope Policy

## Purpose

PASI is a modular system with browser automation, bridge/runtime services, unattended execution, operations tooling, application code, tests, and legacy compatibility layers. Pull requests must preserve those boundaries so changes remain reviewable, testable, reversible, and attributable to one engineering objective.

This policy applies to all new pull requests unless a human maintainer explicitly approves a broader change set.

## Core rule

A pull request has **one primary subsystem and one coherent engineering objective**.

A PR may include a small amount of adjacent code only when that code is a direct dependency of the primary change and the PR would be incomplete or incorrect without it.

A PR must not combine unrelated work from multiple primary subsystems merely because the changes were produced by the same task, automation run, model, or cleanup effort.

Examples of distinct subsystem boundaries include:

- Chromium / ChatGPT browser automation
- local bridge / controller transport
- overnight runner / recovery / task lifecycle
- operations / startup / service management
- legacy or compatibility code
- application/backend features
- tests / CI / developer tooling
- documentation-only changes

A change that intentionally crosses a boundary must explain why the boundary crossing is necessary and identify the dependency that makes the files inseparable.

## Dependency PRs

When a feature requires work in another subsystem, split the work into dependency PRs whenever the changes can be validated independently.

Use this pattern:

1. dependency PR: introduces or repairs the stable interface;
2. primary PR: consumes that interface;
3. optional follow-up PR: cleanup, migration, or retirement after the primary change is verified.

Do not create duplicate implementation across branches just to make PRs appear independent. A dependency that already exists on `main` should be referenced rather than copied.

## Scope justification

Every PR must state:

- the primary subsystem;
- the single engineering objective;
- the intended behavior change;
- why each touched subsystem is necessary;
- any dependency PRs or existing commits;
- the protected boundaries that are intentionally not changed.

For large or cross-cutting PRs, the description must include a file-by-file scope justification.

A PR is considered **large** when any of the following applies:

- more than 15 changed files;
- more than 500 changed lines;
- changes spanning more than two primary subsystems;
- changes to a protected/control-plane area;
- changes that alter public interfaces, policy, recovery semantics, or promotion behavior.

A large PR is not automatically prohibited, but it requires an explicit explanation of why the work cannot be split safely.

## Required validation sections

Every PR must include:

### Tests

State the exact tests/checks run, including any environment-dependent checks that could not be executed.

Do not claim a live/runtime gate is complete from source inspection or unit tests alone.

### Dependencies

List required prerequisite PRs, commits, services, browser extensions, providers, or runtime conditions.

### Rollback

Describe the smallest safe rollback:

- revert the PR;
- disable a feature;
- restore a previous configuration;
- quarantine a generated commit; or
- other concrete recovery action.

For changes to recovery, bridge, security, startup, or promotion behavior, include the expected rollback checkpoint.

### Risk

Identify the failure modes that matter and the evidence used to detect them.

### Scope

List the intended files/modules and explain any adjacent-file exception.

## Prohibited scope patterns

The following should be split unless a human maintainer explicitly approves the combined change:

- Chromium behavior + bridge protocol changes
- bridge changes + overnight engine/recovery changes
- overnight runner changes + unrelated application features
- operations/service startup changes + legacy-controller cleanup
- legacy removal + new feature development
- security/policy changes + unrelated refactors
- broad test rewrites mixed with unrelated production changes
- mass deletion or renaming bundled with functional changes

Do not use a PR as a container for every change produced by an unattended run.

## Autonomous-run rule

An unattended agent must treat this policy as a hard planning constraint.

When the generated work spans multiple primary subsystems:

- stop and partition the work;
- identify dependency order;
- create bounded PR-sized tasks;
- preserve existing work on `main`;
- do not recreate closed/redundant PRs;
- do not force unrelated changes into the same branch solely to reach a green state.

The task ledger should record the PR scope and subsystem so repeated automation cannot silently rebuild the same cross-cutting PR.

## Protected changes

Changes to this policy, the PR template, protected-path rules, promotion controls, sandbox rules, or other governance controls require explicit human review.

An agent must not weaken this policy merely to make a generated change easier to merge.

## Maintainer exception

A maintainer may approve a broader PR when splitting would materially increase risk, duplicate interfaces, or make a coherent migration impossible.

The PR description must record:

- the reason splitting is unsafe or misleading;
- the exact subsystems involved;
- the dependency relationship;
- the validation strategy;
- the rollback checkpoint.

The exception is for reviewability and correctness, not for convenience.

## Review standard

A reviewer should be able to answer, from the PR alone:

1. What one engineering problem is being solved?
2. What subsystem owns the change?
3. Why is every touched file required?
4. What prerequisite state does it depend on?
5. What tests prove the intended behavior?
6. How would the change be rolled back if it regresses?

When those questions cannot be answered without reconstructing unrelated history, the change should be split before merge.
