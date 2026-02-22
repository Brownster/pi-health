# Phase 1 Release Validation and Signoff

Date: 2026-02-22  
Scope: Phase 1 foundation (`PH1-001` through `PH1-009`)  
Branch: `feature/ui-phase1-foundation`

## Decision
GO for Phase 1 foundation release.

Phase 1 objectives are met:
1. Flask serves v2 assets with safe SPA fallback semantics.
2. Runtime mode contract (`legacy|hybrid|v2`) is implemented and covered.
3. Protected v2 placeholder route enforces existing auth/session model.
4. Bundle budgets are enforced in CI.
5. v2 Playwright foundation smoke covers desktop/phone/tablet with mode and auth checks.

## Validation Evidence

### Automated evidence (executed 2026-02-22)
1. `pytest tests/test_app.py -q` -> `49 passed, 1 skipped`
2. `pytest tests/e2e/test_v2_foundation.py -q` -> `24 passed, 3 skipped`
3. `pytest tests/e2e/test_mobile_viewport_smoke.py -q` -> `9 passed`
4. `npm --prefix frontend run build` -> pass
5. `node scripts/check_frontend_bundle_budget.mjs` -> pass

### Budget evidence
1. Initial JS gzip: `65.58 kB` (budget `<= 200 kB`)
2. Initial CSS gzip: `4.10 kB` (budget `<= 80 kB`)
3. Dynamic route chunks: none yet (per-route budget check currently informational)

## Phase 1 Exit Criteria

| Exit Criterion | Status | Evidence |
|---|---|---|
| Flask can serve v2 assets and SPA fallback safely | Pass | `app.py` v2 route handlers + `tests/test_app.py` (`TestV2Routes`) |
| Runtime mode contract implemented and tested | Pass | `app.py` mode parser + redirects + `tests/test_app.py` (`TestUiRuntimeModes`) |
| One protected v2 route works with existing auth model | Pass | `frontend/src/components/auth/*`, `frontend/src/app/App.tsx`, `tests/e2e/test_v2_foundation.py` |
| Bundle budgets enforced in CI | Pass | `.github/workflows/tests.yml` (`frontend-bundle-budget`) + `scripts/check_frontend_bundle_budget.mjs` |
| Desktop/phone/tablet v2 smoke coverage passing | Pass | `tests/e2e/test_v2_foundation.py` |
| Rollback can be done via env only | Pass | Verified contract below |

## Manual Checklist Mapping

| Checklist Item | Status | Evidence |
|---|---|---|
| Legacy routes still stable | Pass | `pytest tests/test_app.py -q`, `pytest tests/e2e/test_mobile_viewport_smoke.py -q` |
| `/v2` shell loads | Pass | `tests/e2e/test_v2_foundation.py::test_v2_shell_viewport_matrix` |
| Mode toggles route behavior correctly | Pass | `tests/e2e/test_v2_foundation.py::test_mode_switch_for_containers_route` |
| Auth guard works on protected v2 route | Pass | `tests/e2e/test_v2_foundation.py::test_v2_containers_auth_guard` |

## Rollback Procedure (Env-only)
1. Set `PIHEALTH_UI_MODE=legacy`.
2. Unset or ignore `PIHEALTH_UI_V2_PAGES`.
3. Restart the service/process.

Expected effect:
1. Legacy routes serve legacy HTML directly.
2. `/v2` routes return disabled/404 behavior.
3. API endpoints remain unchanged.

## Deferred Non-Blocking Follow-ups
1. Add request-cancellation support to v2 auth refresh path (`AbortSignal` usage in provider call sites).
2. Add a loading animation treatment for protected-route auth loading state.
3. Revisit v2 font stack order for Pi OS defaults (current fallback works; optional visual tuning).
