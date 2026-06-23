# Phase 2 Containers Pilot - Implementation Tickets

Date: 2026-02-22  
Branch: `feature/ui-phase2-containers-pilot` (recommended)  
Source: `Docs/UI_MODERNIZATION_PLAN_phase2.md` (Phase 2)  
Precondition signoff: `Docs/UI_PHASE1_RELEASE_SIGNOFF.md`

## Objective
Deliver `/v2/containers` at functional parity for desktop/phone/tablet, then enable hybrid rollout for the containers route with rollback safety preserved.

## Scope Guardrails
1. Preserve existing backend API contracts (`/api/containers*`, `/api/network-test`).
2. Keep rollback instant via `PIHEALTH_UI_MODE` and `PIHEALTH_UI_V2_PAGES`.
3. Preserve mobile baseline from Phase 0: no horizontal overflow at 390px, touch targets >= 44px, no hover-only interactions.

## Execution Order and Dependencies
| Order | Ticket | Depends On | Critical Path | Status |
|---|---|---|---|---|
| 1 | PH2-001 v2 Containers Read Path + Responsive Layout | PH1-009 | Yes | Complete (2026-02-22) |
| 2 | PH2-002 Containers Lifecycle Actions (start/stop/restart/check/update) | PH2-001 | Yes | Complete (2026-02-22) |
| 3 | PH2-003 Containers Logs + Diagnostics Modals | PH2-002 | Yes | Complete (2026-02-22) |
| 4 | PH2-004 Stats Polling + Network Rate Parity | PH2-001 | Yes | Complete (2026-06-23) |
| 5 | PH2-005 Accessibility + Mobile Interaction Hardening | PH2-002..PH2-004 | No | Complete (2026-06-23) |
| 6 | PH2-006 Playwright v2 Containers Parity Suite | PH2-002..PH2-005 | Yes | Pending |
| 7 | PH2-007 Hybrid Rollout Validation (`containers` route) | PH2-006 | Yes | Pending |
| 8 | PH2-008 Phase 2 Release Signoff | PH2-007 | Yes | Pending |

## PH2-001 - v2 Containers Read Path + Responsive Layout (P0)
Owner: Pi-Health maintainers  
Estimate: 1.0 day

### Files
- `frontend/src/pages/containers-page.tsx` (new)
- `frontend/src/lib/containers.ts` (new)
- `frontend/src/lib/format.ts` (new/extend)
- `frontend/src/app/routes.tsx`
- `tests/e2e/test_v2_foundation.py` (route expectation update)

### Tasks
1. Replace placeholder with authenticated data-backed containers page.
2. Render responsive table (desktop) and card/list (mobile/tablet) with zero page overflow.
3. Add filter controls (`all`, `running`, `stopped`) and refresh control.
4. Add deterministic polling cadence and "last updated" indicator.
5. Keep action area visually present but no regression in touch hit area.

### Acceptance Criteria
1. `/v2/containers` shows live container rows for authenticated users.
2. At 390x844 and 768x1024, containers route has no horizontal overflow.
3. Filters and refresh work without full-page reload.
4. Existing `test_v2_foundation.py` passes with updated expected route content.

### Status
Complete (2026-02-22)

### Evidence
1. Placeholder replaced with live data-backed page (`frontend/src/pages/containers-page.tsx`).
2. Route wiring updated (`frontend/src/app/routes.tsx`).
3. Typed containers API + formatting helpers added:
   - `frontend/src/lib/containers.ts`
   - `frontend/src/lib/format.ts`
4. v2 foundation e2e expectations updated for new containers page heading and overflow assertion:
   - `tests/e2e/test_v2_foundation.py`
5. Validation:
   - `npm --prefix frontend run check` -> pass
   - `npm --prefix frontend run build` -> pass
   - `npm --prefix frontend run build:publish` -> pass
   - `pytest tests/e2e/test_v2_foundation.py -q` -> `24 passed, 3 skipped`

## PH2-002 - Containers Lifecycle Actions (P0)
Owner: Pi-Health maintainers  
Estimate: 1.0 day

### Files
- `frontend/src/pages/containers-page.tsx`
- `frontend/src/lib/containers.ts`

### Tasks
1. Implement start/stop/restart/check-update/update actions.
2. Add per-row loading/disabled states during in-flight actions.
3. Refresh row state after action completion and handle filter transitions.

### Acceptance Criteria
1. All lifecycle actions are reachable on phone/tablet and desktop.
2. Action requests call existing backend endpoints and show success/error feedback.
3. No duplicate requests while action is in progress for the same row/action.

### Status
Complete (2026-02-22)

### Evidence
1. Lifecycle action API helper added in `frontend/src/lib/containers.ts`:
   - `runContainerAction(containerId, action)`
   - server-reported error payloads are surfaced as thrown errors.
2. v2 containers page now renders full lifecycle control set on desktop + mobile:
   - `start`
   - `stop`
   - `restart`
   - `check_update`
   - `update`
   (`frontend/src/pages/containers-page.tsx`)
3. Per-row in-flight state/locking implemented:
   - row action lock map (`pendingActions`)
   - duplicate action suppression via ref guard
   - row controls disabled while row action is in progress.
4. Post-action state refresh implemented:
   - after every action completion, containers list is re-fetched and filter view re-evaluated.
5. User feedback added:
   - info/success/error action notice cards at page level with timed dismissal for non-error notices.
6. Validation:
   - `npm --prefix frontend run check` -> pass
   - `npm --prefix frontend run build` -> pass
   - `npm --prefix frontend run build:publish` -> pass
   - `node scripts/check_frontend_bundle_budget.mjs` -> pass
   - `pytest tests/e2e/test_v2_foundation.py -q` -> `24 passed, 3 skipped`

## PH2-003 - Containers Logs + Diagnostics Modals (P0)
Owner: Pi-Health maintainers  
Estimate: 1.0 day

### Files
- `frontend/src/pages/containers-page.tsx`
- `frontend/src/components/*` (modal primitives if extracted)
- `frontend/src/lib/containers.ts`

### Tasks
1. Add logs modal wired to `/api/containers/<id>/logs`.
2. Add container network test modal wired to `/api/containers/<id>/network-test`.
3. Add host network test panel wired to `/api/network-test`.

### Acceptance Criteria
1. Logs and network diagnostics are fully usable from mobile/tablet.
2. Modal content areas are overflow-safe and dismissible.
3. Error states are visible and do not block future retries.

### Status
Complete (2026-02-22)

### Evidence
1. API client helpers added in `frontend/src/lib/containers.ts`:
   - `fetchContainerLogs(containerId, tail)`
   - `runContainerNetworkTest(containerId)`
   - `runHostNetworkTest()`
2. v2 containers diagnostics UX implemented in `frontend/src/pages/containers-page.tsx`:
   - per-row `Logs` and `Network Test` controls on desktop + mobile cards
   - logs modal with loading/error/success states and dismiss paths
   - container network modal with status/local IP/public IP/probe/output sections
   - host network diagnostics panel with run/hide behavior and probe output
3. Modal/panel selectors and workflows are covered by e2e in `tests/e2e/test_v2_foundation.py`:
   - new `test_v2_containers_diagnostics_workflow` with deterministic API mocks
   - validates logs modal, container network modal, and host network panel behavior
4. Validation:
   - `npm --prefix frontend run check` -> pass
   - `npm --prefix frontend run build` -> pass
   - `npm --prefix frontend run build:publish` -> pass
   - `node scripts/check_frontend_bundle_budget.mjs` -> pass
   - `pytest tests/e2e/test_v2_foundation.py -q` -> `30 passed, 6 skipped`

## PH2-004 - Stats Polling + Network Rate Parity (P0)
Owner: Pi-Health maintainers  
Estimate: 0.75 day

### Files
- `frontend/src/pages/containers-page.tsx`
- `frontend/src/lib/containers.ts`

### Tasks
1. Mirror legacy cadence: baseline fetch + stats polling.
2. Compute network rate deltas between polls and render rx/tx rate text.
3. Preserve graceful placeholders when stats are unavailable.

### Acceptance Criteria
1. CPU/memory/network metrics refresh without full table re-render flicker.
2. Network cells show total/rate values with sane fallback behavior.
3. Polling cleanup on unmount is verified.

### Status
Complete (2026-06-23)

### Evidence
1. Split poll cadence implemented in `frontend/src/pages/containers-page.tsx`, mirroring the
   legacy initial-path mechanism (baseline structure fetch, then stats poll):
   - `loadContainers` now fetches structure only (`includeStats: false`) and carries last-known
     metrics forward via `containersRef` **only for containers still running**, so structural
     refreshes never blank live telemetry between samples while a running -> stopped transition
     correctly drops stale stats (matches legacy null-stats behavior for non-running containers).
   - new `pollStats(sourceContainers)` fetches `/api/containers/stats` for running ids only
     (matches legacy `fetchContainerStats` running-only behavior) and merges metric fields.
   - a `refreshNow(reason)` helper chains baseline -> stats; the 10s poll, the manual refresh
     button, and the error retry button all use it so telemetry and the "last updated" timestamp
     stay consistent. `statsInFlightRef` suppresses overlapping polls.
2. Network rate parity matches legacy math (`static/js/pages/containers.js` `calculateNetworkRate`):
   - `rxRate/txRate = max(0, (current - previous) / elapsedSeconds)` keyed per container, using
     `previousNetworkStatsRef` byte counters + `lastStatsFetchRef` timestamp.
   - new `NetworkCell` renders rate (`formatRatePerSecond`) when a prior sample exists, and falls
     back to cumulative totals (`formatBytes`) on the first sample / unavailable stats.
3. Polling cleanup verified: the effect clears the single interval and sets `isMountedRef=false`;
   both `loadContainers` and `pollStats` guard all state writes behind `isMountedRef`.
4. Deterministic stats mock added for the new dependency in `tests/e2e/test_v2_foundation.py`
   (`/api/containers/stats` GET branch).
5. Validation:
   - `npm --prefix frontend run check` -> pass
   - `npm --prefix frontend run build:publish` -> pass
   - `node scripts/check_frontend_bundle_budget.mjs` -> pass (initial JS gzip 71.79 kB / 200 kB)
   - `pytest tests/e2e/test_v2_foundation.py -q` -> `30 passed, 6 skipped`

## PH2-005 - Accessibility + Mobile Interaction Hardening (P1)
Owner: Pi-Health maintainers  
Estimate: 0.5 day

### Tasks
1. Verify 44px minimum touch targets for all controls.
2. Add keyboard/focus handling for row menus and dialogs.
3. Add aria labels and semantic announcements where needed.

### Acceptance Criteria
1. Critical controls are keyboard reachable and screen-reader labeled.
2. No hover-only affordances remain on v2 containers.

### Status
Complete (2026-06-23)

### Evidence
1. Touch targets: the shared `Button` primitive already enforces `min-h-11` (44px) across all
   sizes, so every lifecycle/diagnostic/filter/refresh control meets the 44px minimum. The
   desktop "Open" web-UI link was given `min-h-11 inline-flex` for parity.
2. Dialog focus management consolidated into `ModalOverlay` (`frontend/src/pages/containers-page.tsx`):
   - moves focus into the dialog on open (first focusable element),
   - traps Tab/Shift+Tab within the dialog,
   - closes on Escape (per-dialog; the prior global keydown effect was removed),
   - restores focus to the triggering control on close.
   Logs and container-network dialogs already carry `role="dialog"`, `aria-modal="true"`, and
   `aria-labelledby`.
3. Screen-reader announcements:
   - action notice card is `role="status"` with `aria-live` (`assertive` for errors, otherwise
     `polite`); loading card is `role="status"` `aria-live="polite"`.
   - the update-available glyph is `role="img"` with `aria-label="Update available"`.
   - network cells mark the arrow glyphs `aria-hidden` and add sr-only
     download/upload/received/sent labels.
4. No hover-only affordances: all controls are always-visible buttons/links; hover styles are
   purely decorative enhancements (verified on desktop table and mobile cards).
5. Validation:
   - `npm --prefix frontend run check` -> pass
   - `npm --prefix frontend run build:publish` -> pass
   - `node scripts/check_frontend_bundle_budget.mjs` -> pass (initial JS gzip 73.86 kB / 200 kB)
   - `pytest tests/e2e/test_v2_foundation.py -q` -> `30 passed, 6 skipped` (incl. dialog
     open/close workflow with the new focus management)

## PH2-006 - Playwright v2 Containers Parity Suite (P0)
Owner: Pi-Health maintainers  
Estimate: 0.75 day

### Files
- `tests/e2e/test_v2_containers_parity.py` (new)
- `tests/e2e/conftest.py` (reuse fixtures as needed)

### Tasks
1. Add viewport matrix parity checks for v2 containers (desktop/phone/tablet).
2. Add overflow assertions before and after action/modal workflows.
3. Add mocked action + logs + network flows for deterministic CI behavior.

### Acceptance Criteria
1. CI executes parity suite with stable pass/fail behavior.
2. Tests cover core lifecycle and diagnostics flows on mobile/tablet.

## PH2-007 - Hybrid Rollout Validation (`containers`) (P0)
Owner: Pi-Health maintainers  
Estimate: 0.5 day

### Tasks
1. Validate routing behavior in `legacy|hybrid|v2` with containers enabled.
2. Confirm rollback by switching mode back to `legacy`.
3. Confirm no backend API behavior changes.

### Acceptance Criteria
1. `hybrid` with `PIHEALTH_UI_V2_PAGES=containers` redirects only containers route.
2. Rollback to `legacy` restores legacy containers page without rebuild.

## PH2-008 - Phase 2 Release Signoff (P0)
Owner: Pi-Health maintainers  
Estimate: 0.5 day

### Files
- `Docs/UI_PHASE2_RELEASE_SIGNOFF.md` (new)
- `Docs/UI_PHASE2_CONTAINERS_TICKETS.md` (status updates)

### Tasks
1. Run targeted validation matrix (unit + e2e parity + foundation smoke).
2. Record go/no-go decision with evidence and deferred items.
3. Document rollback confirmation steps.

### Acceptance Criteria
1. Phase 2 exit criteria are documented with evidence.
2. Rollback procedure is tested and recorded.
