# Frontend implementation roadmap

## Phase 1 — Consolidate and modernize CSS

**Status: in progress**

- [x] Establish canonical design tokens.
- [x] Create `web/app.css` as the single application stylesheet entrypoint.
- [x] Add shared accessibility/mobile ergonomics layer.
- [x] Document component ownership and migration rules.
- [ ] Trace every legacy selector to a component owner.
- [ ] Move active rules into `design-system.css` or feature-owned styles.
- [ ] Remove legacy stylesheet files one at a time after regression tests.

## Phase 2 — Refactor JavaScript architecture

**Status: next**

- [ ] Inventory every global function and event listener.
- [ ] Define shell/runtime ownership.
- [ ] Introduce a small shared API/state utility without changing endpoint contracts.
- [ ] Migrate feature controllers incrementally.
- [ ] Retain compatibility shims until all callers are migrated.
- [ ] Remove duplicate handlers only after browser smoke coverage proves equivalence.

## Phase 3 — Feature UX

**Status: partially complete**

### Chat

- [x] Consistent New Chat action and keyboard shortcut.
- [x] Composer auto-sizing and multiline behavior.
- [x] Thinking/tool/source presentation primitives.
- [ ] Attachment progress/error states.
- [ ] Better retry/regenerate affordances.
- [ ] Conversation-level context controls.

### Projects/files

- [x] Project tools and file-row primitives.
- [ ] Explicit folder breadcrumb/current-folder state.
- [ ] Accessible multi-select toolbar.
- [ ] Keyboard file operations.
- [ ] Drag/drop insertion zones with non-drag alternatives.
- [ ] Batch confirmation and progress feedback.

### Calculations

- [x] Discipline → group → calculator information architecture.
- [x] Search across the calculation catalog.
- [ ] Structured unit-aware input presentation.
- [ ] Assumption and traceability panel.
- [ ] Result summary with uncertainty/status where provided by the calculator.
- [ ] Professional result tables/charts where the underlying deterministic model produces series data.

## Phase 4 — Testing and optimization

- [x] JavaScript syntax validation.
- [x] Frontend contract smoke test.
- [x] Browser/API smoke test.
- [ ] Automated accessibility assertions for labels, focus, and dialog behavior.
- [ ] Responsive viewport matrix: 360, 390, 768, 1024, 1440+.
- [ ] Performance marks for first shell render and major view transitions.
- [ ] Remove unnecessary asset requests after CSS/JS consolidation.
- [ ] Manual keyboard and screen-reader audit.

## Phase 5 — Documentation and handoff

- [x] Design-system token documentation.
- [x] Component library contract.
- [x] Current-state assessment.
- [x] Implementation roadmap.
- [ ] Add contributor checklist for new UI components.
- [ ] Add release checklist covering accessibility, responsive behavior, API compatibility, and regression tests.

## Definition of done

A frontend change is complete only when:

1. Existing backend endpoints remain unchanged unless a backend change is explicitly approved.
2. Existing feature behavior remains available.
3. Keyboard and pointer interaction both work.
4. Loading, empty, success, and failure states are intentional.
5. Dark/light themes use canonical tokens.
6. Reduced-motion preferences are respected.
7. Automated frontend/browser checks pass.
8. New CSS/JS has an explicit ownership location and is documented when it establishes a reusable pattern.
