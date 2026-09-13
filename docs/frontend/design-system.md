# Frontend design system

## Purpose

The web client is a vanilla JavaScript application. This document defines the visual and interaction contract so new features do not add another one-off CSS/interaction layer.

## Current architecture

`web/styles.css` remains the compatibility baseline. Existing hardening/polish files are intentionally retained while their active rules are migrated. `web/design-system.css` is the canonical token/component foundation and is loaded immediately before `web/ui-completion.css`, which owns the current navigation/calculation completion components.

Do not delete or merge legacy files solely by filename. Before removal, trace selectors and behavior, migrate active rules to the canonical layer, run the frontend contract/browser checks, and verify the affected views.

## Tokens

| Token family | Canonical values | Use |
| --- | --- | --- |
| Surface | `--ui-bg`, `--ui-surface`, `--ui-surface-2`, `--ui-surface-3` | page, cards, controls, hover/raised surfaces |
| Text | `--ui-text`, `--ui-text-2`, `--ui-text-3` | primary, secondary, metadata |
| Border | `--ui-border`, `--ui-border-strong` | default and emphasized boundaries |
| Accent | `--ui-accent`, `--ui-accent-strong`, `--ui-accent-soft` | primary actions, focus, engineering navigation |
| Status | `--ui-success`, `--ui-warning`, `--ui-danger` | semantic feedback |
| Radius | `--ui-radius-sm`, `--ui-radius-md`, `--ui-radius-lg` | controls, inputs, cards |
| Space | `--ui-space-1` through `--ui-space-10` | 4px-based rhythm |
| Typography | `--ui-font-sans`, `--ui-font-mono` | UI copy and equations/code |

Dark mode overrides the same token names under `body.dark`; components should not hard-code a second dark palette.

## Interaction rules

- Every interactive control has a visible `:focus-visible` treatment.
- Primary actions use the accent button; secondary actions use outlined controls; destructive actions use semantic danger styling when exposed.
- Hover motion is limited to small elevation/translation changes. `prefers-reduced-motion` disables non-essential transitions.
- Forms should preserve server errors and display actionable feedback rather than silently falling back.
- Keyboard shortcuts must never fire while the user is typing in an input, textarea, select, or contenteditable region.
- Escape closes transient navigation and mobile sidebar state.

## Navigation

### New chat

There is one canonical New Chat action. The sidebar button is the primary discoverable action and advertises `Ctrl+O`; the header action is a compact secondary entry point. Both invoke the existing application state transition rather than creating a parallel chat implementation.

### Calculations

The information architecture is intentionally hierarchical:

`Calculations → Engineering discipline → Calculation group → Calculator`

The sidebar opens disciplines. Expanding a discipline reveals its groups and counts. Selecting a group opens a dedicated group page. Search can jump directly to calculator results without changing the underlying catalog.

The source of truth remains `src/calculation_catalog.py`; the UI derives groups from `subcategories` and never duplicates calculator implementations.

## Responsive behavior

- Desktop: persistent sidebar plus optional project tools pane.
- Tablet: reduced navigation width and flexible main content.
- Mobile: collapsible sidebar, single-column cards, full-width search/forms, touch-sized controls.
- Content must remain usable without horizontal scrolling at narrow widths.

## Component contract

Use these patterns for new UI:

- `.primary-button`: one primary action per local context.
- `.outline-button`: secondary action.
- `.quiet-button` / `.quiet-icon`: low-emphasis utility action.
- `.page`, `.page-head`, `.page-title`, `.page-subtitle`: page shell.
- `.page-card` / `.calculation-card`: selectable content cards.
- `.empty-state`, `.loading-state`, `.error-state`: explicit async/data states.
- `.calculation-group-card`: navigation into a calculation group.
- `.status-dot` plus `.status-success|warning|danger`: semantic status indicators.

## Consolidation roadmap

1. Keep `styles.css` as compatibility baseline while migrating selectors into semantic components.
2. Move duplicate tokens/colors/spacing from polish layers into `design-system.css`.
3. Replace repeated page/card/input declarations with canonical component classes.
4. Fold stable interaction behavior into focused modules rather than adding another global patch file.
5. Delete a legacy CSS/JS layer only after selector/event tracing and the full browser/API contract suite pass.
6. Keep this document updated when a new reusable component or interaction pattern is introduced.
