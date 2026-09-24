# Public release boundary

The private PASI repository remains the source of truth.

The public release is generated as a separate snapshot rather than by deleting
private files from the private repository. This is deliberate: deleting a file
from the current branch does not remove its earlier contents from Git history.

## Public allowlist

Only these tracked paths are exported:

- `automation/chromium/pasi-chatgpt/`
- `automation/vscode/pasi-readonly/`

The exporter then writes a small public README, security policy, gitignore,
CodeQL workflow, and snapshot marker.

## Private by design

The public snapshot excludes the private backend/application implementation,
self-hosted runner bootstrap and service control, long-running automation and
planner logic, provider routing, private roadmaps, development logs, and
operator/runtime configuration.

The public snapshot is therefore an intentional client surface, not an
open-source copy of the entire private PASI system.

## History boundary

Do not make the existing private repository public merely because these paths
are absent from a new commit. Its earlier commits would remain visible.

Publish the generated snapshot as a separate repository. This preserves the
private repository's history and makes the public repository's history start
at the already-sanitized boundary.
