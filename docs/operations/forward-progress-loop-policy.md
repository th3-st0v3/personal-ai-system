# PASI Forward-Progress and Repair-Loop Policy

## Purpose
PASI keeps its existing safety, deterministic verification, recovery, and regression-hardening methodology. This policy adds a bounded decision point for repeated failed code repairs so unattended work cannot accumulate patches against the same unresolved failure indefinitely.

The rule changes the **repair strategy**, not the required correctness standard.

## Core rule
A repair cycle is allowed to continue while it produces new engineering information or acceptance progress.

Meaningful progress includes:

- closing an acceptance criterion;
- changing or isolating the root cause;
- adding meaningful regression coverage for a newly identified failure mode;
- materially improving reliability or performance without regressing an existing contract;
- establishing or correcting an architectural boundary.

A repair that only makes another attempt at the same underlying failure does not create forward progress.

## Guard thresholds

The unattended engine uses two bounded thresholds:

- **3 consecutive identical normalized failure signatures**;
- **2 consecutive code-repair cycles with the same normalized root-cause family and no newly discovered root cause**.

The second threshold is intentionally lower because repeating the same root cause twice is enough evidence that incremental patching is no longer producing useful information.

Infrastructure, provider-limit, authentication, ambiguous/non-evaluated, and response-contract failures are not treated as code-repair loops.

## Root-cause reset

When a threshold is reached, PASI:

1. preserves the failure evidence;
2. records the task as **blocked/incomplete** in the durable task ledger;
3. records a `repair_loop_reset` runtime event;
4. resets the per-task retry counters;
5. asks the deterministic planner for another eligible task;
6. continues only with that separately selected task.

The blocked task is not marked complete and is not silently discarded.

An operator can explicitly retry a blocked task later after correcting the underlying problem or re-scoping the work.

## What the guard never does

The guard must never:

- weaken a failing test;
- remove acceptance criteria;
- skip required validation;
- bypass security or authorization controls;
- declare an incomplete task complete;
- suppress evidence of the failure;
- silently change the task's scope to make the failure disappear.

## Relationship to normal bounded retries

The existing per-attempt and per-task retry limits remain in effect.

The repair-loop guard is a second boundary:

  attempt retries -> repair cycle -> repeated-root-cause detection -> root-cause reset

This preserves the benefit of trying reasonable repairs while preventing an unattended task from spending the remainder of a long-running session repeatedly modifying the same broken path.

## Relationship to the hybrid planner

The planner remains authoritative for task sequencing.

A repair-loop reset does not allow the executor model to choose the next task. The blocked task remains unsatisfied in the ledger, while the planner recomputes the next eligible work from dependency and completion state.

This preserves deterministic dependency ordering and the existing planner/worker separation.

## Verification evidence

The implementation records:

- exact failure signature;
- normalized root-cause signature;
- consecutive same-failure count;
- consecutive same-root-cause count;
- repair-reset count;
- blocked-task evidence;
- selected next task.

These fields are persisted in runner state and included in the durable handoff summary.

## Development rhythm

The preferred engineering cadence becomes:

**Implement -> targeted validation -> repair defects -> verify acceptance -> freeze -> advance**

Further optimization or hardening remains valid as a separate engineering objective after the acceptance contract is satisfied.

The metric is not minimum bug-fix commits. The metric is **verified capability gained per engineering cycle while preserving the existing safety and correctness boundaries**.
