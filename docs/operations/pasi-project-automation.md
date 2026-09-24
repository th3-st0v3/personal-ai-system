# PASI Project automation

This repository uses one repository-side GitHub Actions path for roadmap Project synchronization:

- `.github/workflows/pasi-project-metadata.yml` — adds `roadmap` issues to the PASI Project, formats phase metadata when the hidden PASI metadata block exists, and verifies the Project state.
- `scripts/sync_pasi_project_metadata.py` — owns the deterministic Project field/iteration reconciliation.

GitHub Projects still needs its built-in **Auto-add to project** workflow enabled. The repository workflow is the source-controlled fallback/reconciler and metadata formatter; it does not replace the Project UI automation.

## Repository configuration

In **Repository → Settings → Secrets and variables → Actions**, configure:

| Name | Kind | Value |
| --- | --- | --- |
| `PASI_PROJECT_OWNER` | Repository variable | `th3-st0v3` |
| `PASI_PROJECT_NUMBER` | Repository variable | The exact number of the user-owned PASI Project |
| `PASI_PROJECT_TITLE` | Repository variable | Optional exact Project title; recommended for deterministic targeting |
| `PASI_PROJECTS_TOKEN` | Repository secret | Token that can update the target user-owned Project |

The workflow fails closed when the Project number or write-capable token is missing. Do not put the token in a repository variable.

The exact Project number is intentionally not hard-coded in this repository because it is an account-owned Project setting.

## Project UI settings to enable

GitHub documents Project auto-add under **Project → Workflows → Auto-add to project**. See [GitHub: adding items automatically](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/adding-items-automatically).

### 1. Auto-add roadmap issues

Open the PASI Project, then:

1. Open the **…** project menu.
2. Select **Workflows**.
3. Under **Default workflows**, select **Auto-add to project**.
4. Click **Edit**.
5. Under **Filters**, select repository **`th3-st0v3/personal-ai-system`**.
6. Use this filter:
   ```
   is:issue label:roadmap
   ```
7. Click **Save and turn on workflow**.

The filter intentionally matches every roadmap-labeled issue, including backend phase issues, frontend phase issues, and roadmap/coordination issues. GitHub's auto-add workflow supports `is` and `label` filters. On GitHub Free, only one auto-add workflow is available, so use the existing **Auto-add to project** workflow rather than creating duplicates.

### 2. Set initial Status for newly added issues

GitHub documents the built-in **Item added to project** workflow under Project → Workflows. See [GitHub: using the built-in automations](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-built-in-automations).

Configure:

1. **Project → … → Workflows**.
2. Under **Default workflows**, open **Item added to project**.
3. Click **Edit**.
4. Under **When**, select **Issues**. Pull requests are not required for PASI roadmap issue intake.
5. Under **Set**, select **Status: Todo**.
6. Click **Save and turn on workflow**.

The built-in workflow is intentionally limited to static Project-field actions. The PASI synchronizer uses GitHub's native scheduling controls: `Start date`, `Target date`, `Quarter`, and `Iteration`. Quarter membership is selected from the native Quarter iteration windows using the phase Start/End dates, so a phase belongs to the Quarter whose native window fully contains that phase.

### 3. Dynamic metadata and native issue controls

The synchronizer manages:

- native `Start date` and `Target date`;
- native `Quarter` iteration membership, based on the native quarter's date window;
- native `Iteration` membership, with one configured iteration and date window for every PASI phase;
- Project `Status` and the FE roadmap checkbox state;
- native issue `Milestone`;
- native issue `Relationships` for parent/blocked-by/blocking dependencies; and
- native `Development` branch creation when requested.

For each frontend phase, **FE-P0 through FE-P22 map one-to-one to issues #319 through #341 and Iteration 1 through Iteration 23**. The repository Action validates that mapping, reconciles the Project Iteration catalog, and reads the fields back for verification.

Project **Status is authoritative for completion** of the frontend roadmap:
- **Todo** or **In Progress** → the corresponding FE roadmap checkbox remains unchecked.
- **Done** → the corresponding FE roadmap checkbox is checked.
- Closing an FE phase issue moves its Project Status to **Done**.
- Reopening an FE phase issue moves its Project Status back to **Todo**.
- The roadmap checkbox is therefore a derived view of Project Status; it should not be used as a second independent source of truth.

The Project automation runs on roadmap issue changes and on an hourly schedule so a direct Project Status change is reconciled back into the FE roadmap even when no issue event occurs.

## Existing roadmap backfill

GitHub notes that enabling Auto-add does **not** add existing matching items retroactively. See [GitHub: adding items automatically](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/adding-items-automatically).

For the existing PASI roadmap, use the repository Action manually:

1. Open **Actions → PASI Project Automation**.
2. Click **Run workflow**.
3. Select the target branch containing this workflow.
4. Leave **Issue number** empty.
5. Leave **Bulk synchronization scope** as **roadmap**.
6. Run the workflow.

This adds every existing `roadmap`-labeled issue to the Project, formats any issue containing `PASI_PROJECT_METADATA`, and verifies the resulting Project state.

The **metadata** bulk scope remains available for targeted reconciliation of only issues carrying the PASI metadata block.

## Roadmap workflow integration

The repository's existing `pasi-development` workflow now exposes a `project-sync` control mode. This is the preferred operator entry point when the Project needs a synchronized roadmap backfill or reconciliation.

Run:

1. **Actions → pasi-development → Run workflow**.
2. Select the branch containing the roadmap workflow.
3. Set **Development action** to `project-sync`.
4. Set **Project synchronization scope** to `roadmap` for all roadmap-labeled issues, or `metadata` for only issues carrying the PASI metadata block.
5. Keep the normal roadmap path at `roadmaps/pasi-default.json`.
6. Run the workflow.

The `pasi-development` verify job must pass first. The Project sync then calls the reusable `PASI Project Automation` workflow and passes `PASI_PROJECTS_TOKEN` explicitly. The reusable workflow remains independently triggered by roadmap issue events, so new or edited roadmap issues do not depend on a manual development run.

GitHub supports reusable workflows through `workflow_call`, including explicit inputs and secrets. citeturn705596search2turn705596search3

### Automation layers

| Layer | Responsibility |
| --- | --- |
| Project **Auto-add to project** | Automatically adds matching `label:roadmap` issues to the PASI Project. |
| Project **Item added to project** | Applies the initial Project status such as `Todo`. |
| `pasi-development` → `project-sync` | Verifies the repository roadmap, then invokes Project reconciliation on demand. |
| `PASI Project Automation` | Adds missing membership, formats PASI phase metadata, and verifies Project field state. |

This keeps the Project UI responsible for membership automation while the repository workflows own deterministic metadata and verification.

### Frontend roadmap synchronization contract

| FE phase | GitHub issue | Project iteration | Checkbox source |
| --- | ---: | --- | --- |
| FE-P0 … FE-P22 | #319 … #341 | Iteration 1 … Iteration 23 | Project Status |

The mapping is deterministic: FE-Pn uses the corresponding Pn phase schedule and Iteration n+1. The parent frontend roadmap is issue **#318**. Its phase-map checkboxes are reconciled from the Project item’s Status field during each synchronization run.

### FE phase identity safeguards

Before changing a frontend phase's Project Status or its #318 checkbox, the synchronizer scans all repository issues and requires exactly one valid identity for each FE-P0 through FE-P22 phase. It checks:

- the canonical issue number (#319–#341);
- the `FE-P# —` phase identity in the title;
- the frontend/roadmap labels; and
- the frontend `PASI_PROJECT_METADATA` phase when present.

A phase is **skipped with a workflow warning** when its issue is missing, renamed so the phase identity is lost, replaced by another issue, or duplicated. A duplicate can be detected from either the phase title or the frontend metadata block. The synchronizer never guesses which duplicate should receive the checkbox update.

If the #318 roadmap contains a valid phase but points its checkbox link at a different issue than the resolved canonical phase issue, the synchronization fails closed for that mismatch rather than changing the wrong box.

When an FE phase issue (#319–#341) is **closed**, the workflow uses the explicit `--complete-frontend` path. It verifies that the issue is a frontend phase, sets the corresponding Project Status to **Done**, and synchronizes that phase's checkbox on #318 to **[x]**. Reopening the phase returns Project Status to **Todo** and the checkbox to **[ ]**.

## Ongoing behavior

When the repository owner creates, edits, labels, or reopens a roadmap issue, the repository workflow receives the event and:

1. confirms the issue carries the `roadmap` label;
2. confirms the event was authored by `th3-st0v3`;
3. adds the issue to the configured PASI Project if it is not already present;
4. formats the deterministic phase fields when PASI metadata is present;
5. verifies Project membership and all phase field values.

The owner-only gate is intentional because this workflow runs on the existing self-hosted runner and holds a Project-write token.

## Required label convention

New phase issues must carry:

- Backend: `backend`, `roadmap`
- Frontend: `frontend`, `roadmap`, `vertical-slice`

The PASI issue templates establish those defaults. Existing frontend phase issues have been backfilled with the `roadmap` label so the Project auto-add filter catches them.

## Operational note

The repository-side workflow and the Project built-in Auto-add workflow can both observe the same issue. The synchronizer first reads the Project membership and only performs the Project-add mutation when the issue is not already present, so duplicate workflow activity does not intentionally create duplicate Project items.


## Native GitHub issue controls

For roadmap items that need editable Project metadata at creation time, use **PASI Roadmap Item** from the issue-template chooser.

| Issue Form field | Native GitHub target | Behavior |
| --- | --- | --- |
| Description | Project Description | Stored in the Project text field |
| Start Date | Project Start date | Stored as the native Project date |
| End Date | Project Target date | Stored as the native Project date |
| Relationship | Issue Relationships | Supports parent, blocked-by, and blocking specifications; unsupported relationship types are reported without creating a custom field |
| Milestone | Issue Milestone | Must match an existing repository milestone; the issue's native Milestone setting is updated |
| Development | Issue Development | `create branch: <name>` creates a linked branch; `link <existing-branch>` is reported as a manual-link operation |
| Status | Project Status | Stored in the native Project Status field |

The active PASI Project's **Quarter** and **Iteration** are both native iteration fields. Iteration 1 through Iteration 23 are reconciled to the phase schedule with inclusive Start/End windows. Quarter membership is not derived from calendar labels such as Q3/Q4; it is selected by containment in the Project's configured Quarter windows.

GitHub's native issue Relationships UI supports parent/sub-issue and blocking/blocked-by relationships, while issue dependencies can also be managed by the REST API/GraphQL. GitHub's Development section supports creating a branch linked to an issue; linking an existing branch remains a manual UI operation. citeturn456805search0turn456805search3turn456805search1turn456805search2

The synchronizer no longer creates or uses custom Project text fields for Relationship, Milestone, or Development. Any legacy custom fields that were created by an earlier synchronizer revision are not authoritative and can be removed from the Project manually after the native controls are verified.

The issue form is the data-entry surface. GitHub renders submitted issue-form values into the issue body as Markdown, so the synchronizer parses the labeled sections rather than expecting JSON.
