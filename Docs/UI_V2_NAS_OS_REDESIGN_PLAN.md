# v2 NAS OS Redesign Plan

Date: 2026-06-26  
Status: In progress  
Owner: Pi-Health maintainers  
Design source: `Docs/nas-os-ui-update/project/NAS OS.dc.html`  
Screenshot reference: `Docs/nas-os-ui-update/project/uploads/Screenshot_20260626_190330.png`

## Objective

Move the React v2 UI to the NAS OS visual system before migrating more pages. The redesign should change the shared shell and page primitives first, then restyle the already migrated v2 pages. New v2 migration work should continue only after the redesigned primitives are in place.

## Assumptions

1. PH3-007 (`/v2/mounts`), PH3-008 (`/v2/shares`), PH3-009 (`/v2/settings`), and PH3-006b are complete.
2. The target design is the dark sidebar "Console" direction shown in `NAS OS.dc.html` and `Screenshot_20260626_190330.png`.
3. Existing backend API contracts stay unchanged.
4. The rollout model stays unchanged: `PIHEALTH_UI_MODE=legacy|hybrid|v2` and `PIHEALTH_UI_V2_PAGES`.
5. Legacy static pages remain available until v2 phase signoff.
6. Mobile requirements remain hard gates: no horizontal overflow at 390px, 44px touch targets, and no hover-only controls.

## Start Gate

Start this redesign only when these conditions are true:

1. PH3-007 and PH3-008 are merged.
2. `npm --prefix frontend run check` passes.
3. The relevant v2 e2e suites for containers, stacks, disks, storage, mounts, and shares pass.
4. The maintainer confirms the target direction is `NAS OS.dc.html` / `Screenshot_20260626_190330.png`.

## Branch Strategy

Use one focused branch:

`feature/ui-v2-nas-os-redesign`

Do not mix new backend features into this branch. If PH3-006b or PH3-009 starts during this work, build it against the redesigned primitives or hold it until this branch merges.

## Progress

Started: 2026-06-27

1. RD-000 decisions are fixed: use the `limeos` product label, dark-only styling, and grouped navigation without changing route paths.
2. RD-001 has its first complete pass: Lime OS colors, typography stacks, focus colors, and dark browser controls are active.
3. RD-002 has its first complete pass: the desktop sidebar, mobile header, accessible drawer, active-route states, account footer, and sign-out action are implemented.
4. RD-003 has its first complete pass: cards, buttons, badges, status badges, page headers, and metric bars use the Lime OS visual system. Shared table styles will land with the page-restyling work.
5. RD-004 has its first complete pass: `/v2` now shows live system metrics and Docker web services, polls every 30 seconds, and preserves partial data when one API fails.
6. RD-005 has its first complete pass: Containers, Stacks, Disks, Plugins, Pools, Mounts, Shares, and Settings use Lime OS headers, status badges, action colors, dense layouts, and responsive management cards. Existing consoles, editors, confirmations, mounts, shares, SMART, backup, and update workflows retain full parity.
7. RD-007 has its first complete pass: the production bundle builds at 92.60 kB gzip, and the complete v2 e2e suite passes with 91 tests passed and 6 expected legacy-mode skips.

## Route Scope

Treat these pages as already migrated and in scope for restyling:

| Route | Expected state at redesign start | Redesign scope |
|---|---|---|
| `/v2` | Existing foundation dashboard | Replace with NAS OS home dashboard pattern |
| `/v2/containers` | Complete | Restyle table, mobile cards, filters, actions, diagnostics |
| `/v2/stacks` | Complete | Restyle cards, action console, editor, logs, backups |
| `/v2/disks` | Complete | Restyle disk cards/tables, SMART modal, actions |
| `/v2/plugins` | Complete | Restyle plugin list, details, command output |
| `/v2/pools` | Complete | Restyle pool/plugin management views |
| `/v2/mounts` | Complete by assumption | Restyle mounts and media path workflows |
| `/v2/shares` | Complete by assumption | Restyle shares workflow |
| `/v2/settings` | Complete | Restyle self-update, backups, and auto-update workflows |

Keep these routes as next-build targets after the redesign:

| Route | Recommendation |
|---|---|
| `/v2/system` | Build after redesign using the design's `system_metrics` screen |
| `/v2/apps` or `/v2/catalog` | Build after redesign using the design's `app_catalog` screen |
| `/v2/network`, `/v2/tools`, `/v2/tailscale` | Build after core restyle and settings |

## Execution Plan

### RD-000 - Confirm Design Details

Estimate: 0.25 day  
Critical path: Yes

Tasks:

1. Record the chosen screenshot and HTML prototype as the baseline.
2. Display the product name as `limeos`.
3. Use a dark-only shell and remove the visible theme toggle.
4. Decide route labels for `Apps` vs `Catalog`, `Storage` vs `Disks/Pools/Mounts/Shares`, and `System Health` vs `System`.

Acceptance criteria:

1. The design details are fixed before code changes start.
2. The shell nav labels are fixed before implementation starts.

### RD-001 - Design Tokens and Global CSS

Estimate: 0.5-1 day  
Critical path: Yes

Files:

- `frontend/src/styles/globals.css`
- `frontend/src/components/theme/*`

Tasks:

1. Add NAS OS color tokens:
   - background `#0a0d12`
   - sidebar `#0d1117`
   - panel `#11161d`
   - panel border `#1d2530`
   - divider `#1b222c`
   - text `#e6edf3`
   - muted text `#8b97a6`
   - dim text `#5a6573`
   - accent lime `#c7f24a`
   - success `#3fb950`
   - warning `#e3a008`
   - danger `#f85149`
   - info `#58a6ff`
2. Switch typography to IBM Plex Sans and IBM Plex Mono.
3. Set the app to dark-first styling.
4. Decide whether to remove, hide, or preserve the current theme toggle.
5. Keep reduced-motion handling.

Acceptance criteria:

1. Global tokens match the design.
2. Existing pages still render after token changes.
3. TypeScript check passes.

### RD-002 - Shell, Navigation, and Mobile Drawer

Estimate: 1-2 days  
Critical path: Yes

Files:

- `frontend/src/components/layout/app-shell.tsx`
- `frontend/src/app/routes.tsx`
- optional: `frontend/src/components/layout/nav-items.ts`

Tasks:

1. Replace the top nav with a fixed desktop sidebar.
2. Add grouped navigation:
   - Main: Home, System Health
   - My Apps: Containers, Stacks, App Catalog
   - System: Storage, Network, Tools, Settings
3. Map current v2 routes into those groups without breaking route paths.
4. Add a mobile top bar and slide-in drawer below 980px.
5. Add a scrim that closes the drawer.
6. Move signed-in user display and logout affordance to the sidebar footer.
7. Preserve auth behavior and protected routes.

Acceptance criteria:

1. Desktop shows the sidebar layout.
2. Phone and tablet show the mobile top bar and drawer.
3. Keyboard users can open, navigate, and close the drawer.
4. Active route styling matches the NAS OS accent treatment.
5. No horizontal overflow at 390x844 or 768x1024.

### RD-003 - Shared UI Primitives

Estimate: 1-1.5 days  
Critical path: Yes

Files:

- `frontend/src/components/ui/card.tsx`
- `frontend/src/components/ui/button.tsx`
- `frontend/src/components/ui/modal-overlay.tsx`
- new shared primitives as needed under `frontend/src/components/ui/`

Tasks:

1. Update `Card` to match NAS OS panels: 8-11px radius, dark panel fill, thin border, no glass styling.
2. Update `Button` variants:
   - primary lime
   - panel outline
   - success
   - warning
   - danger
   - info
   - ghost
3. Add shared `Badge`, `StatusBadge`, `MetricBar`, and `PageHeader` primitives if they reduce repeated page styles.
4. Add a shared table wrapper/header style for dense management tables.
5. Update modal panels to match the new cards and keep focus trapping.

Acceptance criteria:

1. Existing pages can use the new primitives without page-local color rewrites for common controls.
2. Action colors are consistent across containers, stacks, disks, mounts, shares, and storage.
3. Modal focus behavior remains covered by existing tests.

### RD-004 - Home Dashboard Restyle

Estimate: 1 day  
Critical path: Yes

Files:

- `frontend/src/pages/dashboard-home.tsx`
- possibly new API helper if live metrics are added

Tasks:

1. Replace the foundation-status placeholder with the NAS OS `web_services` dashboard pattern.
2. Show service/app cards using real available data where practical.
3. Add the metric strip if current APIs already provide the data cheaply.
4. Keep placeholder text minimal where data is not wired yet.

Acceptance criteria:

1. `/v2` looks like a real product dashboard, not a migration placeholder.
2. No new backend contract is required for the first pass.
3. Empty/loading/error states remain readable.

### RD-005 - Restyle Completed v2 Pages

Estimate: 3-5 days  
Critical path: Yes

Files:

- `frontend/src/pages/containers-page.tsx`
- `frontend/src/pages/stacks-page.tsx`
- `frontend/src/pages/disks-page.tsx`
- `frontend/src/pages/storage-page.tsx`
- `frontend/src/pages/mounts-page.tsx`
- `frontend/src/pages/shares-page.tsx` once PH3-008 lands

Tasks:

1. Replace page headers with the shared NAS OS page header pattern.
2. Convert page-local cards to the shared NAS OS card primitive.
3. Restyle containers desktop table to match the design's `docker_containers` table.
4. Restyle containers mobile cards without reducing action access.
5. Restyle stacks cards, progress bars, and action groups.
6. Restyle disks and partition rows to match `disk_management`.
7. Restyle storage plugins, pools, mounts, and shares using the same panel/list grammar.
8. Keep all existing data fetching, polling, modals, and actions intact.

Acceptance criteria:

1. No API contract changes.
2. All migrated pages share the same visual system.
3. Existing e2e workflow tests still pass after selector updates.
4. Phone/tablet overflow checks pass for every redesigned route.

### RD-006 - Navigation Coverage and Placeholders

Estimate: 0.5-1 day  
Critical path: No

Files:

- `frontend/src/app/routes.tsx`
- `frontend/src/pages/coming-soon-page.tsx`

Tasks:

1. Add or update placeholder routes for pages not yet built in v2:
   - system health
   - app catalog
   - network
   - tools
   - settings
   - tailscale if it remains separate
2. Use the new placeholder design.
3. Keep legacy fallback links visible where the route is not yet migrated.

Acceptance criteria:

1. Every sidebar item has a sensible destination.
2. Unmigrated pages clearly offer a legacy fallback.
3. Placeholder routes do not appear complete when they are not complete.

### RD-007 - Test and Build Hardening

Estimate: 1-2 days  
Critical path: Yes

Files:

- `tests/e2e/test_v2_foundation.py`
- `tests/e2e/test_v2_containers_parity.py`
- `tests/e2e/test_v2_stacks_parity.py`
- `tests/e2e/test_v2_disks_parity.py`
- `tests/e2e/test_v2_storage_parity.py`
- `tests/e2e/test_v2_mounts_parity.py`
- `tests/e2e/test_v2_shares_parity.py` once PH3-008 lands

Tasks:

1. Update tests that assert old shell text or top-nav behavior.
2. Add shell tests for desktop sidebar and mobile drawer.
3. Keep existing workflow tests for actions, logs, modals, editors, and diagnostics.
4. Run bundle budget checks.
5. Run the full relevant v2 e2e set.

Acceptance criteria:

1. `npm --prefix frontend run check` passes.
2. `npm --prefix frontend run build:publish` passes.
3. `node scripts/check_frontend_bundle_budget.mjs` passes.
4. v2 foundation and parity e2e suites pass.

## Follow-On Migration Order

After the redesign branch lands, continue Phase 3 in this order:

1. PH3-009 Settings + Backup/Update workflows.
2. PH3-006b Storage plugin schema config editor + install wizard, if still pending.
3. System Health v2 page, using the design's `system_metrics` screen.
4. App Catalog v2 page, using the design's `app_catalog` screen.
5. Network, Tools, and Tailscale.
6. PH3-010 parity and rollout suite.
7. PH3-011 release signoff.

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Screenshot and HTML prototype diverge in small layout details | Rework | Treat `Screenshot_20260626_190330.png` as the visual baseline and `NAS OS.dc.html` as implementation detail reference |
| Page-local Tailwind classes fight the new design tokens | Slow restyle | Update shared primitives first, then pages |
| Mobile sidebar introduces focus or scroll regressions | Usability regression | Add drawer keyboard and overflow tests in RD-007 |
| Theme toggle conflicts with dark-only design | Extra scope | Decide in RD-000; default recommendation is dark-only for v2 redesign |
| Restyling large pages breaks workflows | Functional regression | Keep API/data logic untouched and run existing parity tests after each page |

## Estimated Effort

Expected effort: 7-10 working days after PH3-007 and PH3-008 merge.

Best case: 5-7 days if the redesign stays close to shared primitives and no light-mode support is required.

Higher-confidence case: 8-12 days if every existing modal, table, and mobile card needs close visual parity with the prototype.

## Definition of Done

1. The v2 shell matches the NAS OS sidebar design on desktop and mobile.
2. All currently migrated v2 pages use the new visual system.
3. Existing workflows still work: container actions, logs, diagnostics, stack actions/editors/backups, disk actions, storage commands, mounts, and shares.
4. All redesigned routes pass desktop, phone, and tablet overflow checks.
5. Hybrid rollout behavior remains unchanged.
6. Legacy pages remain available until final v2 signoff.
