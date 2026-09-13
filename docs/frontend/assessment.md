# Frontend assessment

## Current state

The workspace already has a strong functional shell: chat, projects, calculations, simulations, notes/files, evidence, authentication UI, and search are represented in a single application surface. The current markup is intentionally small, which is a good fit for the vanilla-JavaScript constraint.

The main architectural weakness is not missing functionality; it is **layer accumulation**. The frontend has a 34 KB application controller plus many specialized interaction modules and several CSS layers. The same selectors are intentionally restyled by later files, which makes ownership difficult to reason about and increases regression risk.

The shell currently references one canonical stylesheet entrypoint (`web/app.css`), which now preserves the historical cascade behind one application-level contract. The next consolidation step should migrate active rules into the canonical design system and delete compatibility files only after selector-level regression coverage proves they are no longer needed.

## Highest-priority pain points

### P0 — Architecture clarity

- Multiple JavaScript files can own overlapping interaction behavior.
- Multiple CSS files redefine shell selectors such as navigation, chat, buttons, and responsive layout.
- Global functions are retained for compatibility, so ownership is not always obvious.

**Recommendation:** establish explicit runtime ownership: shell/accessibility, application state/API, feature controllers, and presentation utilities. Migrate one surface at a time.

### P0 — Accessibility

- The application has good semantic foundations, labels, reduced-motion support, and visible focus rules, but dynamic focus management and mobile navigation need a single owner.
- Dialog focus restoration/trapping should be centralized rather than duplicated by feature code.

**Recommendation:** use `accessibility-runtime.js` as the cross-cutting owner and keep feature code responsible only for its own controls/content.

### P1 — Chat experience

The chat is the product's primary surface and already supports assistant content, code, images, tool activity, sources, model selection, and attachments. The opportunity is to make those states feel like one coherent system: clear generation state, reliable message actions, better source/tool grouping, and strong mobile composition.

### P1 — Project/file experience

The existing file rows and project tools provide the right primitives, but a mature engineering workspace should make hierarchy, selection, current folder, batch actions, and drag/drop state immediately legible.

### P1 — Calculations

The new hierarchy is substantially clearer: `Calculations → Discipline → Group → Calculator`. The next improvement is execution presentation: structured inputs, units, assumptions, validation, result hierarchy, equation/model visibility, and traceability should read as one professional engineering instrument.

### P2 — Performance

The current application is small enough for the browser, but many script/style layers increase request and parsing overhead. The canonical CSS entrypoint is a safe first step. JavaScript should be consolidated only after dependency/side-effect tracing; blindly concatenating scripts could change initialization order.

## Visual direction

Use a restrained technical palette: neutral surfaces, high-contrast text, one cool engineering accent, and semantic status colors. Typography should distinguish interface copy from equations/code. Motion should communicate state rather than decorate the interface.

The current design tokens in `design-system.css` provide the foundation. New surfaces should use those tokens rather than introduce local colors, spacing values, or radii.

## Recommended priority order

1. Preserve and test current behavior.
2. Establish canonical CSS/JS ownership.
3. Finish chat interaction states.
4. Finish project/file hierarchy and batch workflows.
5. Upgrade calculator execution/result presentation.
6. Add performance instrumentation and reduce asset overhead.
7. Perform keyboard, contrast, responsive, and screen-reader audits.

## Effort estimate

For one experienced full-stack developer working incrementally:

| Workstream | Estimate |
| --- | ---: |
| CSS migration/consolidation | 2–4 days |
| JS ownership/state refactor | 3–6 days |
| Chat polish | 1–3 days |
| Project/files UX | 2–4 days |
| Calculation result UX | 2–4 days |
| Accessibility audit/fixes | 2–3 days |
| Performance/browser validation | 1–2 days |
| Documentation/handoff | 1 day |

These are engineering estimates, not promises of elapsed calendar time. Existing backend/API compatibility remains the governing constraint.
