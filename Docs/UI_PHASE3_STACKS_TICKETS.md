# Phase 3 Stacks Pilot - Implementation Tickets

Date: 2026-06-25
Branch: `feature/ui-phase2-containers-pilot` (continuing) or a new `feature/ui-phase3-stacks` branch
Source: `Docs/UI_MODERNIZATION_PLAN_phase2.md` (Phase 3)
Precondition: Phase 2 containers pilot complete + signed off (`Docs/UI_PHASE2_RELEASE_SIGNOFF.md`)

## Objective
Deliver `/v2/stacks` at functional parity with the legacy stacks page for desktop/phone/tablet,
reusing the Phase 2 pilot primitives (responsive layout, modals, polling, shared e2e fixtures),
then enable hybrid rollout for the `stacks` route with rollback safety preserved.

## Decisions in force
1. Migrate **Stacks first** (this pilot).
2. Keep the **current v2 visual style**; the nasOS re-skin is a separate later pass (see
   memory `v2-nasos-theme-direction`). Do not introduce nasOS tokens/fonts/sidebar here.

## Scope Guardrails
1. Preserve existing backend API contracts in `stack_manager.py` (`/api/stacks*`). No backend redesign.
2. Keep rollback instant via `PIHEALTH_UI_MODE` and `PIHEALTH_UI_V2_PAGES` (routing is already
   generic: `serve_ui_page('stacks', 'stacks.html')` + page-key redirect).
3. Preserve the Phase 0 mobile baseline: no horizontal overflow at 390px, touch targets >= 44px,
   no hover-only interactions.
4. Reuse Phase 2 primitives: `Button`/`Card`, `ModalOverlay` (focus trap + scroll lock),
   shared e2e fixtures in `tests/e2e/conftest.py`, bundle-budget gate.

## Stacks API surface (stack_manager.py)
- `GET /api/stacks?status=true` — list (`name`, `status`, `running_count`, `container_count`, compose path)
- `POST /api/stacks/scan` — rescan stacks dir
- `GET /api/stacks/<name>` — details (compose content, status, env content/has_env)
- `POST /api/stacks/<name>` — create/update ; `DELETE /api/stacks/<name>` — delete
- `GET|POST /api/stacks/<name>/compose` — read/write compose file
- `GET|POST /api/stacks/<name>/env` — read/write env file
- `POST /api/stacks/<name>/{up,down,restart,pull}` — lifecycle (non-streaming)
- `GET /api/stacks/<name>/{up,down,restart,pull}/stream` — lifecycle with streamed output (EventSource)
- `GET /api/stacks/<name>/logs?tail=N` — logs
- `GET /api/stacks/<name>/status` — status
- `GET /api/stacks/<name>/backups`, `GET .../backups/<backup_name>`, `POST .../restore` — backups

### Notable new element vs containers
Lifecycle actions have a **GET streaming variant** (`/<action>/stream`) that emits live command
output. The pilot will consume this via `EventSource` and render a live action console, with a
graceful fallback to the non-streaming `POST /<action>` when streaming is unavailable. This is the
main technical addition relative to the containers pilot.

## Execution Order and Dependencies
| Order | Ticket | Depends On | Critical Path | Status |
|---|---|---|---|---|
| 1 | PH3-001 v2 Stacks Read Path + Responsive Layout | PH2-008 | Yes | Complete (2026-06-25) |
| 2 | PH3-002 Stack Lifecycle Actions + Streaming Console | PH3-001 | Yes | Pending |
| 3 | PH3-003 Compose + Env Editors | PH3-001 | Yes | Pending |
| 4 | PH3-004 Logs + Backups/Restore + Create/Delete/Scan | PH3-002 | No | Pending |
| 5 | PH3-005 Accessibility + Mobile Interaction Hardening | PH3-002..PH3-004 | No | Pending |
| 6 | PH3-006 Playwright v2 Stacks Parity Suite | PH3-002..PH3-005 | Yes | Pending |
| 7 | PH3-007 Hybrid Rollout Validation (`stacks` route) | PH3-006 | Yes | Pending |
| 8 | PH3-008 Phase 3 Release Signoff | PH3-007 | Yes | Pending |

## PH3-001 - v2 Stacks Read Path + Responsive Layout (P0)
### Files
- `frontend/src/pages/stacks-page.tsx` (new)
- `frontend/src/lib/stacks.ts` (new — typed client + normalizers)
- `frontend/src/app/routes.tsx` (add `/stacks`)
- `frontend/src/components/layout/app-shell.tsx` (add Stacks nav item)
- `tests/e2e/test_v2_foundation.py` (shell/nav expectation if needed)

### Tasks
1. Typed `fetchStacks({ includeStatus })` client against `GET /api/stacks?status=true`, with
   normalizers mirroring `containers.ts` (null-safe fields).
2. Responsive stack list: per-stack card showing name, status badge, `running_count/container_count`
   services-up, compose path; desktop and mobile layouts with zero horizontal overflow.
3. Deterministic polling cadence + "last updated" indicator (reuse the containers pattern).
4. Refresh control; empty/loading/error states.
5. Route + nav wiring; `/v2/stacks` renders for authenticated users.

### Acceptance Criteria
1. `/v2/stacks` shows live stack rows for authenticated users.
2. No horizontal overflow at 390x844 and 768x1024.
3. Refresh works without full-page reload; polling cleans up on unmount.
4. Frontend `check` + `build:publish` + bundle budget pass.

### Status
Complete (2026-06-25)

### Evidence
1. Typed client `frontend/src/lib/stacks.ts`: `fetchStacks({ includeStatus })` against
   `GET /api/stacks?status=true`, null-safe `normalizeStack`, `getStackServicesPercent` helper;
   surfaces the list endpoint's `error` field as a thrown error.
2. `frontend/src/pages/stacks-page.tsx`: responsive stack-card grid (1col mobile -> 3col xl) with
   status badge, running/container services-up bar, compose filename; loading/empty/error states;
   10s polling with `isMountedRef` cleanup; refresh control + "last updated".
3. Route + nav wiring in `frontend/src/app/routes.tsx` (`/stacks`, requiresAuth, showInNav);
   `App.tsx` renders it generically through `ProtectedRoute` and the shell nav.
4. Validation:
   - `npm --prefix frontend run check` -> pass
   - `npm --prefix frontend run build:publish` -> pass
   - `node scripts/check_frontend_bundle_budget.mjs` -> pass (initial JS gzip 74.76 kB / 200 kB)
   - `pytest tests/e2e/test_v2_foundation.py -q` -> `30 passed, 6 skipped` (shell/nav unaffected)

Deferred to later tickets: stack list e2e parity coverage (PH3-006).

## PH3-002 - Stack Lifecycle Actions + Streaming Console (P0)
### Tasks
1. `up/down/restart/pull` actions with per-stack in-flight locking (reuse containers locking model).
2. Live action console consuming `GET /api/stacks/<name>/<action>/stream` via `EventSource`;
   render streamed output in an overflow-safe, dismissible panel/modal.
3. Graceful fallback to `POST /api/stacks/<name>/<action>` when streaming is unavailable; surface
   success/error feedback; refresh stack state on completion.

### Acceptance Criteria
1. All lifecycle actions reachable on phone/tablet/desktop with visible streamed output.
2. EventSource is always closed on completion/unmount (no leaked connections).
3. No duplicate in-flight action for the same stack.

## PH3-003 - Compose + Env Editors (P0)
### Tasks
1. View/edit compose via `GET|POST /api/stacks/<name>/compose` with save + error feedback.
2. View/edit env via `GET|POST /api/stacks/<name>/env`.
3. Overflow-safe editor surfaces on mobile; unsaved-change awareness.

### Acceptance Criteria
1. Compose/env are viewable and savable from mobile/tablet.
2. Server validation/errors are visible and non-blocking for retries.

## PH3-004 - Logs + Backups/Restore + Create/Delete/Scan (P1)
### Tasks
1. Logs modal wired to `/api/stacks/<name>/logs?tail=N` (reuse the containers logs modal pattern).
2. Backups list + download (`/backups`, `/backups/<name>`) and restore (`POST /restore`) with confirms.
3. Create (`POST /api/stacks/<name>`), delete (`DELETE`), and rescan (`POST /api/stacks/scan`).

### Acceptance Criteria
1. Logs, backups/restore, and create/delete/scan are usable on mobile/tablet with confirmations
   on destructive actions.

## PH3-005 - Accessibility + Mobile Interaction Hardening (P1)
### Tasks
1. 44px touch targets; keyboard/focus handling for dialogs/editors (reuse `ModalOverlay`).
2. aria labels + live-region feedback for actions/streaming status.
3. No hover-only affordances.

## PH3-006 - Playwright v2 Stacks Parity Suite (P0)
### Files
- `tests/e2e/test_v2_stacks_parity.py` (new)
- `tests/e2e/conftest.py` (add `install_v2_stacks_api_mocks` fixture; reuse `v2_mode_server`)

### Tasks
1. Viewport matrix (desktop/phone/tablet) parity checks for `/v2/stacks`.
2. Overflow assertions before/after action/editor/modal workflows.
3. Mocked list/action(+stream)/compose/env/logs/backups flows for deterministic CI.

### Acceptance Criteria
1. Stable pass/fail in CI; covers lifecycle + editors + diagnostics on mobile/tablet.

## PH3-007 - Hybrid Rollout Validation (`stacks` route) (P0)
### Tasks
1. Validate `legacy|hybrid|v2` routing with `PIHEALTH_UI_V2_PAGES=stacks`.
2. Confirm rollback to `legacy` restores the legacy stacks page without rebuild.
3. Confirm no backend API behavior change.

## PH3-008 - Phase 3 Release Signoff (P0)
### Files
- `Docs/UI_PHASE3_RELEASE_SIGNOFF.md` (new)
- `Docs/UI_PHASE3_STACKS_TICKETS.md` (status updates)

### Tasks
1. Run validation matrix (unit + e2e parity + foundation smoke + full `tox -e all`).
2. Record go/no-go with evidence and deferred items.
3. Document rollback confirmation steps.
