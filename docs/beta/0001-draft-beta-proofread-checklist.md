# Draft Beta Proofread Checklist

This checklist marks the point at which the technical foundation is ready for human UX/content refinement.

## End-to-end workflows

- [x] Create and select a project.
- [x] Create arbitrarily nested folders.
- [x] Create and edit notes.
- [x] Upload, download, replace, rename, move, copy, paste, duplicate, and delete files.
- [x] Search workspace names and note content.
- [x] Sort workspace items in both directions for name, creation time, and modification time.
- [x] Navigate nested folders with breadcrumbs.
- [x] Run deterministic engineering calculations through one registry and application boundary.
- [x] Display calculation equations, inputs, detailed solution steps, assumptions, limitations, and units.
- [x] Review engineering requirements, sources, evidence, invalidation, and decisions.
- [x] Keep project-scoped workspace and engineering records isolated from other projects.

## Human proofread targets

The remaining work is primarily refinement rather than replacing the foundation:

- Visual hierarchy, spacing, typography, and responsive behavior.
- Better modal/editor experiences in place of browser prompts and confirms.
- Richer keyboard navigation, selection behavior, and context-menu focus management.
- More discoverable engineering evidence entry and review workflows.
- Calculation form usability, unit selection/conversion, and result presentation.
- Additional calculation families, especially reservoir volumetrics, controls, circuits, mechanics, numerical methods, and engineering-specific derived quantities.
- Future plots, simulation views, CAD-oriented workflows, and AI assistance.

## Intentional beta limits

The current launcher is a local draft-beta server, not a production deployment.
Authentication, multi-user authorization, production-grade deployment, durable background jobs, browser-based collaborative editing, and autonomous consequential actions are intentionally outside this milestone.

Financial capabilities remain information-oriented. The current architecture does not provide brokerage access, trade execution, margin control, money movement, or autonomous trading.

## Verification gate

Run:

```bash
PYTHONPATH=src python scripts/smoke_test_beta.py
```

Then run the complete automated suite:

```bash
PYTHONPATH=src python -m unittest discover -s src -p 'test_*.py' -v
```

Finally validate the browser scripts with Node 24:

```bash
node --check web/app.js && node --check web/keyboard.js && node --check web/workspace-root.js && node --check web/workspace-interactions.js && node --check web/engineering.js
```
