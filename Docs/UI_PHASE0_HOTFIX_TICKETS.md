# Phase 0 Mobile Hotfix - Implementation Tickets

Date: 2026-02-22
Branch: `hotfix/mobile-phase0`
Source: `Docs/UI_MODERNIZATION_PLAN_phase2.md` (Phase 0)

## Objective
Ship a standalone mobile usability hotfix in the existing Flask + static HTML + ES module stack, without waiting for any React migration decision.

## Scope Guardrails
1. No backend API contract changes.
2. No feature expansion beyond mobile usability fixes.
3. Keep changes isolated to Phase 0 files and tests.

## Execution Order and Dependencies
| Order | Ticket | Depends On | Critical Path | Status |
|---|---|---|---|---|
| 1 | PH0-001 Mobile Nav Touch Refactor | - | Yes | Implemented (QA passed) |
| 2 | PH0-002 Toast and Notification Mobile Positioning | - | No | Implemented (QA passed) |
| 3 | PH0-003 Containers Responsive Data Layout | PH0-001 (nav visibility check overlap) | Yes | Implemented (QA passed) |
| 4 | PH0-004 Disks Overflow and Dense Layout Fixes | PH0-001 | No | Implemented (QA passed) |
| 5 | PH0-005 Global Shell Responsive Spacing Sweep | PH0-001 | No | Implemented (QA passed) |
| 6 | PH0-006 Mobile/Tablet Playwright Coverage + Overflow Assertions | PH0-001..PH0-005 | Yes | Implemented (QA passed) |
| 7 | PH0-007 Release Validation and Signoff | PH0-006 | Yes | Implemented (QA passed) |

## PH0-001 - Mobile Nav Touch Refactor (P0)
Owner: TBD
Estimate: 0.75 day

### Files
- `static/js/nav.js`
- `static/css/foundation.css` (if needed for shared nav breakpoint classes)

### Tasks
1. Replace hover-dependent nav behavior with explicit click/tap behavior for all dropdown items.
2. Add mobile nav toggle button and collapsible menu state for small viewports.
3. Ensure desktop behavior remains stable while mobile behavior does not rely on `mouseenter`/`mouseleave`.
4. Add Escape-key and outside-click close behavior for open menus.

### Acceptance Criteria
1. At 390x844, user can open nav and reach every top-level section without hover.
2. Dropdown sections open/close by tap and do not get stuck open.
3. At desktop viewport, nav remains usable and active-state highlighting still works.

### Verification
- Manual: login -> open nav -> navigate to `Containers`, `System`, `Settings` on phone viewport.
- Automated: covered by PH0-006 mobile nav smoke tests.

## PH0-002 - Toast and Notification Mobile Positioning (P0)
Owner: TBD
Estimate: 0.5 day

### Files
- `static/js/lib/layout.js`
- `static/js/lib/notify.js`
- `static/js/api.js`

### Tasks
1. Replace fixed desktop top-right width assumptions with mobile-safe placement.
2. Ensure notifications do not clip off-screen at 390px width.
3. Standardize container max-width and safe area spacing for phone/tablet.
4. Verify toast stacking still works while modals are open.

### Acceptance Criteria
1. At 390x844, toasts fully render inside viewport.
2. Multiple stacked notifications remain readable and dismissible.
3. Existing notification behavior on desktop remains intact.

### Verification
- Manual: trigger success/error/info toasts from `containers` and `settings` pages.
- Automated: viewport screenshot/assertion in PH0-006.

## PH0-003 - Containers Responsive Data Layout (P0)
Owner: TBD
Estimate: 1.0 day

### Files
- `static/containers.html`
- `static/css/containers.css`
- `static/js/pages/containers.js`

### Tasks
1. Add a responsive data presentation strategy:
   - Desktop: existing table view.
   - Mobile/tablet: card/list row mode or controlled horizontal scroll container.
2. Ensure action buttons/dropdowns remain reachable in mobile layout.
3. Preserve existing polling, filter, log modal, and network-test behavior.
4. Remove whitespace/column behavior that forces horizontal overflow.

### Acceptance Criteria
1. At 390x844, container page has no horizontal page overflow.
2. User can run start/stop/restart/log/network-test actions on mobile.
3. Filters (`All`, `Running`, `Stopped`) remain functional.
4. Logs modal and container network modal remain usable.

### Verification
- Manual workflow on phone viewport.
- Automated workflow tests in PH0-006.

## PH0-004 - Disks Overflow and Dense Layout Fixes (P1)
Owner: TBD
Estimate: 0.75 day

### Files
- `static/js/pages/disks.js`
- `static/css/disks.css`

### Tasks
1. Fix known overflow hotspots in SMART/details/table regions.
2. Ensure code/output blocks wrap or scroll in contained regions only.
3. Confirm card actions and metadata remain readable and tappable on mobile.

### Acceptance Criteria
1. At 390x844, disks page has no horizontal page overflow.
2. SMART detail sections and action controls remain accessible.
3. Desktop layout behavior does not regress.

### Verification
- Manual page sweep on phone/tablet.
- Overflow assertions in PH0-006.

## PH0-005 - Global Shell Responsive Spacing Sweep (P1)
Owner: TBD
Estimate: 0.5 day

### Files
- `static/*.html` (all routes using `container mx-auto p-6` and related shell classes)
- `static/js/lib/layout.js` (if shell class defaults need updates)

### Tasks
1. Replace desktop-biased spacing classes with responsive spacing utilities.
2. Ensure headers, nav, and main content do not consume excessive vertical space on phone.
3. Normalize mobile spacing so core controls appear above fold where practical.

### Acceptance Criteria
1. No obvious clipped/overlapping shell sections on 390x844.
2. Header/nav/main spacing is consistent across top routes.
3. No desktop spacing regression.

### Verification
- Manual cross-route spot check: `index`, `system`, `containers`, `disks`, `settings`.

## PH0-006 - Playwright Mobile/Tablet Coverage and Overflow Assertions (P0)
Owner: TBD
Estimate: 0.75 day

### Files
- `tests/e2e/conftest.py`
- `tests/e2e/test_containers_page.py`
- `tests/e2e/test_system_metrics.py`
- Additional e2e files as needed for smoke coverage

### Tasks
1. Add Playwright test profiles for desktop, phone (390x844), and tablet (768x1024).
2. Add reusable helper assertion:
   - `document.documentElement.scrollWidth <= window.innerWidth`
3. Add/extend mobile smoke tests for:
   - login path
   - system page rendering
   - containers actions + modal interactions
4. Ensure tests are deterministic and run under existing `pytest -m e2e` flow.

### Acceptance Criteria
1. E2E suite executes in desktop, phone, and tablet profiles.
2. Overflow assertions pass on targeted routes.
3. Containers mobile action workflow passes.

### Verification
- Run selected e2e tests locally or via CI for all three viewport profiles.
- Local execution (2026-02-22):
  - `pytest tests/e2e/test_mobile_viewport_smoke.py -q` -> `9 passed`
  - `pytest tests/e2e/test_containers_page.py tests/e2e/test_ui_workflows.py tests/e2e/test_system_metrics.py -q` -> `9 passed, 7 skipped`

## PH0-007 - Release Validation and Signoff (P0)
Owner: TBD
Estimate: 0.5 day

### Files
- `Docs/UI_MODERNIZATION_PLAN_phase2.md` (status update)
- `Docs/UI_PHASE0_RELEASE_SIGNOFF.md`
- `tests/e2e/test_phase0_release_signoff.py`

### Tasks
1. Execute manual smoke checklist:
   - login/logout/session timeout
   - containers lifecycle actions
   - system metrics/action visibility
2. Document pass/fail results and open defects.
3. Confirm Phase 0 exit criteria from plan are met.
4. Capture final go/no-go decision and publish signoff note.

### Acceptance Criteria
1. Phase 0 exit criteria are explicitly marked pass/fail.
2. Any deferred issues are documented with follow-up ticket IDs.

### Verification
- `pytest tests/e2e/test_phase0_release_signoff.py -q -rs` -> `10 passed, 2 skipped`
- Release decision and exit-criteria evidence captured in `Docs/UI_PHASE0_RELEASE_SIGNOFF.md`.

## Phase 0 Definition of Done
1. `containers` and `system` have no horizontal overflow at 390x844.
2. Navigation is touch-first and fully usable without hover.
3. Core container actions are reachable and functional on phone.
4. Mobile/tablet Playwright coverage is in place and passing for Phase 0 routes.
5. Hotfix can be released independently from any React migration decision.
