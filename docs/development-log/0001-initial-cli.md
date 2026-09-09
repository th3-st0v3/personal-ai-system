# Development Log 0001 — Initial CLI and Project Recovery

## Date

2026-09-08

## Project

Personal AI System / Engineering Evidence Copilot

## Goal

Establish a working foundation for the Personal AI System while preserving
the long-term requirements for learning, research, engineering, project
execution, safety, and future extensibility.

## Requirements recovered

The authoritative requirements document was restored from Git history:

`docs/requirements/SYSTEM-REQUIREMENTS.md`

The requirements establish these immediate priorities:

- Persistent personal context
- Project and task organization
- Structured notes and knowledge capture
- Coding and research assistance
- Safe tool execution boundaries
- User-controlled permissions
- Reliable local data handling

They also establish that multi-agent coordination, advanced automation,
and a broader technical operating system are later-stage capabilities.

## Current implementation

The initial command-line application supports:

- Adding notes
- Viewing notes
- Searching notes
- Asking an AI model through OpenRouter
- Basic missing-key and request-error handling
- SQLite-based local storage

Important files:

- `src/main.py` — command-line interface
- `src/db.py` — database operations
- `src/model.py` — model request handling
- `.gitignore` — excludes local databases and Python cache files

## Verification completed

- Added a note successfully.
- Viewed notes successfully.
- Searched notes successfully.
- Asked the AI successfully.
- Confirmed `notes.db` is ignored by Git.
- Confirmed Python cache files are ignored.
- Committed the initial CLI.
- Pushed the initial CLI to GitHub.

## Git checkpoints

- `628594b` — establish project requirements and architecture
- `bdedd97` — preserve system architecture draft
- `a27a299` — add initial personal AI CLI

## Database situation

The local database contains:

- A `notes` table
- A `projects` table
- A nullable `notes.project_id` column

A local backup named `notes.db.backup` was created before continuing
database work.

The backup remains untracked because it may contain private notes.

A repeated manual migration reported:

`duplicate column name: project_id`

This did not indicate data loss. It indicated that the column had already
been added during an earlier attempt.

## Important lesson

Git tracks application code and documentation, but the local SQLite database
is intentionally ignored. Therefore, database schema changes must be
represented in application code so they can be reproduced on another machine.

## Next milestone

Implement safe database initialization and project-aware notes.

The application should eventually support:

- Creating projects
- Listing projects
- Selecting a project
- Assigning notes to projects
- Searching notes within a project
- Asking questions using project context

## Command-library requirement

Every future development milestone should document the important commands
used, what they do, and whether they are safe to repeat.

The command library should contain practical references for:

- Repository navigation
- Virtual-environment activation
- Running the application
- Running tests
- Inspecting Git status and history
- Reviewing diffs
- Creating commits
- Pushing to GitHub
- Database inspection
- Database backup and recovery
- Safe migration procedures

## Development method

Use one small change at a time:

1. Explain the change.
2. Inspect the relevant code.
3. Make the change.
4. Run focused tests.
5. Review the diff.
6. Explain what was learned.
7. Commit only when stable.

## Current status

The initial CLI is working and pushed.

The requirements document has been recovered.

The next implementation step is safe database initialization.
