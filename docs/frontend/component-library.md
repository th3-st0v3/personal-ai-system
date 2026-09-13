# Frontend component library

## Purpose

The Engineering AI Workspace uses vanilla HTML, CSS, and JavaScript. This document is the implementation contract for reusable UI patterns. New features should compose these patterns instead of introducing another one-off style or event layer.

## Shell

- **Top bar:** persistent global search, account actions, and mobile navigation toggle.
- **Sidebar:** primary workspace navigation, expandable calculations hierarchy, and recent chats.
- **Main view:** one active workspace view; pages render into `#page-view` without replacing the application shell.
- **Project tools:** contextual project actions; hidden when no project context exists.
- **Modal:** one semantic dialog container with a focus trap and focus restoration.

## Actions

| Component | Use | Rule |
| --- | --- | --- |
| `.primary-button` | Primary task completion | One dominant primary action per surface where practical |
| `.outline-button` | Secondary action | Use for navigation or reversible secondary actions |
| `.quiet-button` | Low-emphasis utility | Never use for destructive actions without additional emphasis |
| `.icon-button` | Compact utility | Must have an accessible label when icon-only |
| `.nav-item` | Workspace navigation | Use `data-view` for view routing |

## Cards and lists

- `.page-card` is for navigable summaries.
- `.calculation-group-card` is for a calculation discipline/group.
- `.calculation-card` is for an individual deterministic calculator.
- `.file-row` is for project file/folder entries and may expose batch-selection controls.
- Hover effects are supplemental; selected/active state must remain understandable without hover.

## Forms

- Every field needs a visible label or an accessible name.
- Validation errors must identify the field and explain how to correct it.
- Preserve user input when server validation fails.
- Disable submission only while the operation is actually in flight.
- Do not convert failed API responses into empty/default content.

## Chat

- User messages are visually distinct from assistant responses without relying solely on color.
- Assistant content supports headings, paragraphs, lists, code, images, tool activity, and sources.
- Long-running operations expose a visible thinking/loading state.
- Message actions are discoverable by keyboard even when visually de-emphasized.
- Composer supports multiline input, attachment, model selection, and explicit send/stop state.

## Calculations

Information architecture is intentionally hierarchical:

`Calculations → Discipline → Group → Calculator`

A calculator card should expose at minimum the model name, engineering domain/group, equation/model summary, and result-unit context. The calculator execution surface should preserve assumptions, inputs, deterministic outputs, and traceability information.

## Files and project navigation

- Represent folders/files semantically, not only through color or icons.
- Selection controls must expose checked state to assistive technology.
- Drag-and-drop is an enhancement; every file operation must remain possible with keyboard and pointer controls.
- Destructive batch actions require an explicit confirmation step.

## Responsive behavior

- Desktop: three-region workspace when project context is active.
- Tablet: contextual tools collapse; primary navigation remains accessible.
- Mobile: sidebar becomes a modal-like drawer, main content becomes single-column, and controls meet a practical touch target size.
- Respect safe-area insets on devices with display cutouts/home indicators.

## Accessibility contract

Target WCAG 2.1 AA. In particular:

1. Keyboard focus is always visible.
2. Focus is trapped in dialogs and restored to the invoking control.
3. Escape closes transient navigation.
4. Status changes can be announced through the shared live region.
5. Reduced-motion preferences disable non-essential animation.
6. High-contrast preferences receive stronger boundaries/focus affordances.
7. Color is never the only indication of status or selection.

## Architecture rule

`web/app.css` is the single stylesheet entrypoint. Compatibility styles remain behind that entrypoint during migration so a component can be moved incrementally without changing backend behavior. New canonical tokens belong in `design-system.css`; cross-cutting accessibility rules belong in `accessibility.css`.

Likewise, shared browser behavior should be added to focused runtime modules rather than another page-specific script. Preserve existing global APIs until their callers are migrated and tested.
