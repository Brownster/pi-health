# Phase 1 Foundation - Implementation Tickets

Date: 2026-02-22  
Branch: `feature/ui-phase1-foundation` (recommended)  
Source: `Docs/UI_MODERNIZATION_PLAN_phase2.md` (Phase 1)
Decision record: `Docs/UI_PHASE1_DECISION_GATE.md`

## Objective
Stand up a production-safe v2 foundation (React + Vite + TypeScript + Tailwind 4 + shadcn patterns) under Flask with reversible hybrid routing, without migrating full feature pages yet.

## Preconditions
1. Decision Gate explicitly approved Phase 1+ after Phase 0 completion.
2. Phase 0 remains releasable independently (`Docs/UI_PHASE0_RELEASE_SIGNOFF.md`).
3. Default runtime mode remains `legacy` until Phase 1 signoff.

## Scope Guardrails
1. No backend API contract changes.
2. No full page parity migration in Phase 1 (that starts in Phase 2 with `containers`).
3. Keep instant rollback path via env flags:
   - `PIHEALTH_UI_MODE=legacy|hybrid|v2`
   - `PIHEALTH_UI_V2_PAGES=<comma-separated legacy routes>`

## Execution Order and Dependencies
| Order | Ticket | Depends On | Critical Path | Status |
|---|---|---|---|---|
| 1 | PH1-001 Decision Gate Record + Runtime Contract | - | Yes | Complete (2026-02-22) |
| 2 | PH1-002 Frontend Workspace Bootstrap (React/Vite/TS/Tailwind4) | PH1-001 | Yes | Complete (2026-02-22) |
| 3 | PH1-003 Flask v2 Asset Serving + SPA Fallback | PH1-002 | Yes | Complete (2026-02-22) |
| 4 | PH1-004 Hybrid Route Switch (`legacy`/`hybrid`/`v2`) | PH1-003 | Yes | Complete (2026-02-22) |
| 5 | PH1-005 v2 Auth Guard + Protected Placeholder Route | PH1-004 | Yes | Complete (2026-02-22) |
| 6 | PH1-006 Theme Baseline (modern dark default + dark/light/system) | PH1-002 | No | Complete (2026-02-22) |
| 7 | PH1-007 Bundle Budget Enforcement in CI | PH1-002 | No | Complete (2026-02-22) |
| 8 | PH1-008 Playwright Foundation Smoke for v2 | PH1-005 | Yes | Complete (2026-02-22) |
| 9 | PH1-009 Phase 1 Release Validation and Signoff | PH1-006..PH1-008 | Yes | Complete (2026-02-22) |

## PH1-001 - Decision Gate Record + Runtime Contract (P0)
Owner: Pi-Health maintainers  
Estimate: 0.25 day

### Files
- `Docs/UI_PHASE1_DECISION_GATE.md`
- `Docs/UI_MODERNIZATION_PLAN_phase2.md`
- `Docs/UI_PHASE0_RELEASE_SIGNOFF.md`
- `Docs/UI_PHASE1_FOUNDATION_TICKETS.md` (status updates)

### Tasks
1. Record explicit decision to proceed with Phase 1+.
2. Confirm default deployment mode remains `legacy`.
3. Confirm initial Phase 2 pilot remains `containers`.
4. Record rollback expectation: mode switch can disable v2 immediately.

### Acceptance Criteria
1. Decision to proceed is documented with date and owner.
2. Runtime mode contract is documented and unambiguous.

### Status
Complete (2026-02-22)

## PH1-002 - Frontend Workspace Bootstrap (P0)
Owner: Pi-Health maintainers  
Estimate: 1.0 day

### Files
- `frontend/` (new project root)
- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/tsconfig*.json`
- `frontend/src/main.tsx`
- `frontend/src/app/App.tsx` (or equivalent)
- `frontend/src/styles/globals.css`
- Root docs/build notes as needed

### Tasks
1. Scaffold React 18 + TypeScript + Vite app in `frontend/`.
2. Configure Tailwind CSS 4 and base shadcn-compatible styling setup.
3. Add minimal app shell and route framework for `/v2`.
4. Add production build command and artifact output contract.

### Acceptance Criteria
1. `npm --prefix frontend run build` succeeds.
2. Build output is deterministic and ready for Flask static serving.

### Status
Complete (2026-02-22)

### Evidence
1. `npm --prefix frontend run build` -> pass.
2. `npm --prefix frontend run build:publish` -> pass (`frontend/dist/*` copied to `static/v2/`).
3. Workspace includes Tailwind 4 + shadcn-compatible config (`frontend/components.json`, `@/*` alias, tokenized `src/styles/globals.css`).

## PH1-003 - Flask v2 Asset Serving + SPA Fallback (P0)
Owner: Pi-Health maintainers  
Estimate: 0.75 day

### Files
- `app.py`
- Optional helper module for UI mode parsing

### Tasks
1. Serve built v2 assets from `static/v2/`.
2. Add routes:
   - `/v2`
   - `/v2/<path:path>` (serve file if present, else `index.html`)
3. Ensure missing assets return proper 404s, not SPA fallback.
4. Keep existing legacy routes unchanged.

### Acceptance Criteria
1. `/v2` loads React shell when `static/v2` artifacts exist.
2. `/v2/assets/*` serves static files correctly.
3. Legacy routes (`/containers.html`, `/system.html`, etc.) still behave identically.

### Status
Complete (2026-02-22)

### Evidence
1. New Flask routes in `app.py`: `/v2`, `/v2/`, `/v2/<path:path>`.
2. Asset requests with missing files return 404 (no SPA fallback for asset-like paths).
3. Route-like paths (for example `/v2/containers`) fall back to `static/v2/index.html`.
4. Targeted tests: `pytest tests/test_app.py -q` -> `49 passed, 1 skipped`.

## PH1-004 - Hybrid Route Switch (P0)
Owner: Pi-Health maintainers  
Estimate: 1.0 day

### Files
- `app.py`
- Optional config parser module
- Tests for mode behavior (unit/integration)

### Tasks
1. Implement `PIHEALTH_UI_MODE` with values `legacy`, `hybrid`, `v2`.
2. Implement `PIHEALTH_UI_V2_PAGES` parser (comma-separated route keys).
3. In `hybrid`, redirect only selected legacy pages to `/v2/<page>`.
4. In `legacy`, force all existing routes to legacy templates.
5. In `v2`, prefer v2 routes broadly while preserving API endpoints.

### Acceptance Criteria
1. Mode behavior is deterministic and covered by tests.
2. Switching to `legacy` disables v2 exposure without code changes.

### Status
Complete (2026-02-22)

### Evidence
1. Runtime mode parser implemented in `app.py` (`PIHEALTH_UI_MODE=legacy|hybrid|v2`, invalid values default to `legacy`).
2. Hybrid page parser implemented in `app.py` (`PIHEALTH_UI_V2_PAGES`) with normalization and alias support.
3. Legacy UI routes now route through mode-aware redirect helper (`serve_ui_page`) with:
   - `legacy`: always serve legacy HTML.
   - `hybrid`: redirect only selected page keys.
   - `v2`: prefer v2 routes broadly for legacy page URLs.
4. `/v2` and `/v2/<path:path>` are explicitly disabled in `legacy` mode.
5. Deterministic coverage added in `tests/test_app.py` (`TestUiRuntimeModes`) and validated by:
   - `pytest tests/test_app.py -q` -> `49 passed, 1 skipped`.

## PH1-005 - v2 Auth Guard + Protected Placeholder Route (P0)
Owner: Pi-Health maintainers  
Estimate: 0.75 day

### Files
- `frontend/src/...` auth/session utilities
- `frontend/src/...` router setup
- Optional Flask auth-check route usage tests

### Tasks
1. Use existing `/api/auth/check` and session model for v2 protection.
2. Implement protected placeholder route (suggested: `/v2/containers` placeholder only).
3. Unauthenticated users are redirected to `/login.html`.
4. Keep username/session continuity with current backend model.

### Acceptance Criteria
1. Authenticated user can load protected v2 placeholder route.
2. Unauthenticated request is redirected to login path.

### Status
Complete (2026-02-22)

### Evidence
1. Added frontend auth/session utility against existing backend endpoint (`frontend/src/lib/auth.ts` -> `/api/auth/check`).
2. Added shared auth context for v2 shell (`frontend/src/components/auth/auth-provider.tsx`).
3. Added protected route guard with unauthenticated redirect to `/login.html` (`frontend/src/components/auth/protected-route.tsx`).
4. Marked `/containers` route as protected and wrapped protected routes in `App.tsx`.
5. Preserved session continuity by surfacing authenticated username in v2 shell header.
6. Validation:
   - `npm --prefix frontend run build` -> pass.
   - `npm --prefix frontend run build:publish` -> pass.
   - `pytest tests/test_app.py -q` -> `49 passed, 1 skipped`.

## PH1-006 - Theme Baseline (P1)
Owner: Pi-Health maintainers  
Estimate: 0.75 day

### Files
- `frontend/src/styles/*`
- `frontend/src/components/*` shell primitives
- Optional theme utilities

### Tasks
1. Implement one unified modern theme with `dark|light|system` mode switch.
2. Preserve default visual continuity with current modern dark baseline.
3. Do not block Phase 1 on legacy multi-theme porting.

### Acceptance Criteria
1. Default v2 render matches modern dark expectation.
2. User can switch light/dark/system without layout regressions.

### Status
Complete (2026-02-22)

### Evidence
1. Token baseline updated in `frontend/src/styles/globals.css` with modern-dark continuity values:
   - dark background `#09090b`
   - dark card `#18181b`
   - primary `#3b82f6`
   - muted/border palette aligned to existing modern theme family.
2. Dark/light/system mode switching is available through:
   - `frontend/src/components/theme/theme-provider.tsx`
   - `frontend/src/components/theme/theme-mode-toggle.tsx`
3. Default visual continuity preserved as dark:
   - `ThemeProvider` default mode is `dark`.
   - `frontend/index.html` applies stored theme (or dark fallback) before React mounts to avoid flash.
4. Validation:
   - `npm --prefix frontend run build` -> pass.
   - `npm --prefix frontend run build:publish` -> pass.

## PH1-007 - Bundle Budget Enforcement in CI (P1)
Owner: Pi-Health maintainers  
Estimate: 0.5 day

### Files
- CI workflow config (existing workflow path in `.github/workflows/`)
- Optional budget-check script in `scripts/`

### Tasks
1. Enforce Phase 1 budgets:
   - Initial JS <= 200 KB gzip
   - Initial CSS <= 80 KB gzip
   - Per-route chunk <= 100 KB gzip
2. Fail CI when budgets are exceeded.
3. Publish size summary in CI logs.

### Acceptance Criteria
1. CI gate blocks oversize bundles.
2. Size report is visible to maintainers on each PR.

### Status
Complete (2026-02-22)

### Evidence
1. Added budget-check script: `scripts/check_frontend_bundle_budget.mjs`.
2. Budget gates implemented:
   - Initial JS <= 200 kB gzip
   - Initial CSS <= 80 kB gzip
   - Per-route dynamic chunk <= 100 kB gzip
3. CI integration added in `.github/workflows/tests.yml` as `frontend-bundle-budget` job:
   - `npm --prefix frontend ci`
   - `npm --prefix frontend run build`
   - `node scripts/check_frontend_bundle_budget.mjs`
4. Local validation:
   - `npm --prefix frontend run build` -> pass.
   - `node scripts/check_frontend_bundle_budget.mjs` -> pass.

## PH1-008 - Playwright Foundation Smoke for v2 (P0)
Owner: Pi-Health maintainers  
Estimate: 0.75 day

### Files
- `tests/e2e/conftest.py` (reuse existing viewport matrix)
- New `tests/e2e/test_v2_foundation.py`

### Tasks
1. Add smoke tests for `/v2` shell in desktop/phone/tablet profiles.
2. Add overflow assertion checks on v2 shell at 390x844 and 768x1024.
3. Add mode-switch checks (`legacy`/`hybrid`/`v2`) for one pilot route.
4. Add auth guard checks for protected v2 placeholder.

### Acceptance Criteria
1. v2 shell is reachable and overflow-safe on phone/tablet.
2. Mode switching behavior is validated by e2e tests.
3. Auth redirect behavior is validated.

### Status
Complete (2026-02-22)

### Evidence
1. Added new suite `tests/e2e/test_v2_foundation.py`.
2. Coverage implemented:
   - `/v2` shell smoke across desktop/phone/tablet.
   - Overflow assertions for phone/tablet on v2 shell.
   - Runtime mode checks for `legacy|hybrid|v2` against pilot route behavior.
   - Auth guard checks for protected `/v2/containers` route.
3. Tests use isolated app instances per mode (`legacy|hybrid|v2`) to validate runtime-mode behavior deterministically.
4. CI e2e job now builds/publishes v2 assets before UI tests in `.github/workflows/tests.yml`.
5. Local validation:
   - `pytest tests/e2e/test_v2_foundation.py -q` -> `24 passed, 3 skipped`.

## PH1-009 - Release Validation and Signoff (P0)
Owner: Pi-Health maintainers  
Estimate: 0.5 day

### Files
- `Docs/UI_PHASE1_RELEASE_SIGNOFF.md` (new)
- `Docs/UI_PHASE1_FOUNDATION_TICKETS.md` (status updates)
- Optional updates to `Docs/UI_MODERNIZATION_PLAN_phase2.md`

### Tasks
1. Run manual checklist:
   - legacy routes still stable
   - `/v2` shell loads
   - mode toggles route correctly
   - auth guard works
2. Run targeted automated suite:
   - existing regression subset
   - v2 foundation smoke
3. Record go/no-go and deferred items.

### Acceptance Criteria
1. Phase 1 criteria marked pass/fail with evidence.
2. Rollback instruction is verified and documented.

### Status
Complete (2026-02-22)

### Evidence
1. Signoff artifact created: `Docs/UI_PHASE1_RELEASE_SIGNOFF.md`.
2. Automated validation executed:
   - `pytest tests/test_app.py -q` -> `49 passed, 1 skipped`.
   - `pytest tests/e2e/test_v2_foundation.py -q` -> `24 passed, 3 skipped`.
   - `pytest tests/e2e/test_mobile_viewport_smoke.py -q` -> `9 passed`.
   - `npm --prefix frontend run build` -> pass.
   - `node scripts/check_frontend_bundle_budget.mjs` -> pass.
3. Rollback procedure documented and verified (`PIHEALTH_UI_MODE=legacy`).

## Phase 1 Definition of Done
1. Flask can serve v2 assets and SPA fallback safely.
2. Runtime mode contract (`legacy|hybrid|v2`) is implemented and tested.
3. One protected v2 placeholder route works under existing auth/session model.
4. Bundle budgets are enforced in CI.
5. Desktop/phone/tablet v2 smoke coverage is passing.
6. Phase 1 can be rolled back instantly using env flags only.
