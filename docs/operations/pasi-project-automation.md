
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
| Start Date | Project Start date | Stored as the native Project date |
| End Date | Project Target date | Stored as the native Project date |
| Status | Project Status | Stored in the native Project Status field |

The issue form does **not** contain Description, Relationship, Milestone, or Development text inputs. Description remains the normal issue body. Milestone, Relationships, and Development are the native GitHub issue controls and are edited directly on each phase when needed.

The active PASI Project's **Quarter** and **Iteration** are both native iteration fields. Quarter uses a repeating four-quarter cycle: **Quarter 1, Quarter 2, Quarter 3, Quarter 4, then Quarter 1 again with new dates**. Every configured quarter ends on the **19th**: Quarter 1 is **2026-09-22 through 2026-12-19**, Quarter 2 is **2026-12-20 through 2027-03-19**, Quarter 3 is **2027-03-20 through 2027-06-19**, Quarter 4 is **2027-06-20 through 2027-09-19**, then Quarter 1 repeats **2027-09-20 through 2027-12-19**, followed by Quarter 2 **2027-12-20 through 2028-03-19**. A phase is assigned to the quarter containing its **Start Date**, so the existing phase/iteration dates remain unchanged even when a phase crosses a quarter boundary.

GitHub's native issue Relationships UI supports parent/sub-issue and blocking/blocked-by relationships. GitHub's Development section supports creating a branch linked to an issue, while linking an existing branch remains a native UI operation. citeturn456805search0turn456805search3turn456805search1turn456805search2

The synchronizer no longer creates or uses a custom Project Description field or text-form stand-ins for Relationship, Milestone, or Development. On synchronization it also removes the known legacy custom fields (`Description`, `Relationship`, `Development`, `Development Milestone`, and `PASI Quarter`) when they are ordinary user-created Project fields; GitHub native issue-backed fields such as `Milestone` are preserved.

The roadmap issue form contains only **Start Date**, **End Date**, and **Status**. Description remains normal issue-body content. Milestone, Relationships, and Development are native GitHub issue controls and can be edited directly on each phase when needed.