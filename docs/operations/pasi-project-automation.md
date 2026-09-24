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

The built-in workflow is intentionally limited to static Project-field actions. Dynamic PASI fields such as Start Date, End Date, Team, Quarter, and Iteration are derived from the issue's PASI metadata block by the repository Action.

### 3. Dynamic metadata formatting

No additional Project UI formatter is required for:

- Start Date
- End Date
- Team
- Quarter
- Iteration

The repository Action validates the canonical P0–P22 schedule, preserves existing Project option IDs, reconciles the Iteration 1–23 catalog, writes the fields, and reads them back for verification.

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
