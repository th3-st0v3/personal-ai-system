# Disposable PASI Project-Field Test Task

## Task
- **id:** `test.project-field-integration.20260923`
- **title:** Verify GitHub project task metadata and Development linkage
- **objective:** Verify that one PASI task can be represented with the structured roadmap/task fields and connected to GitHub development work.
- **depends_on:** `P0`
- **acceptance_criteria:**
  - The task uses the PASI structured task fields.
  - The repository task file is committed on the disposable test branch.
  - The GitHub issue is connected to development work through a pull request.
  - Project metadata can be assigned through the connected GitHub Projects interface where supported.
- **verification:**
  - Inspect this task file.
  - Inspect issue #301.
  - Inspect the issue Development section for the linked pull request.

## Project-field test values

| Field | Test value |
|---|---|
| Label | P0 |
| Iteration | Test Iteration |
| Quarter | Q4 2026 |
| Start | 2026-09-23 |
| End | 2026-09-24 |
| Milestone | Test Project Metadata |
| Relationship | P0 / #273 |
| Development | linked draft pull request |

> Disposable integration test. Delete this task, issue, branch, and PR after verification.
