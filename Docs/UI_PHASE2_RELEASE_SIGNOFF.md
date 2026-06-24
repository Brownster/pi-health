# Phase 2 Containers Release Validation and Signoff

Date: 2026-06-23  
Scope: Phase 2 containers pilot (`PH2-001` through `PH2-008`)  
Branch: `feature/ui-phase2-containers-pilot`

## Decision
GO for Phase 2 containers pilot release.

Phase 2 objectives are met:
1. `/v2/containers` has functional parity for container read, action, diagnostics, polling, and network-rate workflows.
2. Desktop, phone, and tablet coverage passes for the v2 containers page and modal workflows.
3. Runtime rollout remains reversible through `PIHEALTH_UI_MODE` and `PIHEALTH_UI_V2_PAGES`.
4. Backend container API contracts remain unchanged across `legacy`, `hybrid`, and `v2` UI modes.
5. Bundle size remains within the Phase 1 budget gates.

## Validation Evidence

### Automated evidence (executed 2026-06-23)
1. `npm --prefix frontend run build:publish` -> pass
2. `node scripts/check_frontend_bundle_budget.mjs` -> pass
3. `pytest tests/ -v -m "not e2e"` -> `540 passed, 1 skipped, 123 deselected`
4. `pytest tests/e2e/test_v2_foundation.py tests/e2e/test_v2_containers_parity.py tests/e2e/test_v2_hybrid_rollout.py -q` -> `44 passed, 6 skipped`
5. `.tox/all/bin/ruff check --select E9,F63,F7,F82 .` -> pass
6. `tox -e all` -> pass (`95 passed, 28 skipped` in full e2e; lint and unit steps passed)

### Budget evidence
1. Vite production output from `build:publish`:
   - Initial JS gzip: `73.86 kB`
   - Initial CSS gzip: `5.95 kB`
2. Bundle budget script:
   - Initial JS gzip: `72.13 kB` (budget `<= 200 kB`)
   - Initial CSS gzip: `5.81 kB` (budget `<= 80 kB`)
   - Dynamic route chunks: none; per-route budget skipped

## Phase 2 Exit Criteria

| Exit Criterion | Status | Evidence |
|---|---|---|
| `/v2/containers` renders live container rows for authenticated users | Pass | `tests/e2e/test_v2_foundation.py::test_mode_switch_for_containers_route` |
| Lifecycle controls are reachable on desktop, phone, and tablet | Pass | `tests/e2e/test_v2_containers_parity.py::test_v2_containers_lifecycle_action_feedback` |
| Logs, container network diagnostics, and host diagnostics work without overflow | Pass | `tests/e2e/test_v2_containers_parity.py::test_v2_containers_overflow_through_workflows` |
| Dialog focus handling is keyboard safe | Pass | `tests/e2e/test_v2_containers_parity.py::test_v2_containers_dialog_focus_trap_and_restore` |
| Stats polling and network rate behavior are covered by the v2 page workflow | Pass | `tests/e2e/test_v2_foundation.py`, `tests/e2e/test_v2_containers_parity.py` |
| Hybrid rollout redirects only selected containers route | Pass | `tests/e2e/test_v2_hybrid_rollout.py::test_hybrid_containers_rollout_redirects_only_selected_route` |
| Rollback restores legacy containers without rebuild | Pass | `tests/e2e/test_v2_hybrid_rollout.py::test_legacy_mode_rollback_restores_legacy_containers_without_rebuild` |
| Container API behavior is mode-independent | Pass | `tests/e2e/test_v2_hybrid_rollout.py::test_container_api_contract_is_unchanged_across_ui_modes` |
| Full project gate passes | Pass | `tox -e all` |

## Rollback Procedure

Use environment variables only; no rebuild is required.

1. Set `PIHEALTH_UI_MODE=legacy`.
2. Unset `PIHEALTH_UI_V2_PAGES` or leave it ignored.
3. Restart the service/process.

Expected result:
1. `/containers.html` serves the legacy containers page.
2. `/v2/containers` returns the legacy-mode disabled response.
3. `/api/containers*` endpoints keep the same payload shape and auth behavior.

Automated rollback evidence:
1. `tests/e2e/test_v2_hybrid_rollout.py::test_legacy_mode_rollback_restores_legacy_containers_without_rebuild`
2. `tests/e2e/test_v2_hybrid_rollout.py::test_container_api_contract_is_unchanged_across_ui_modes`

## Hook State

`core.hooksPath` was restored to `scripts/hooks` after validation. The pre-commit hook runs `tox -e all`.

## Deferred Non-Blocking Follow-ups

1. Expand v2 coverage to additional legacy pages after containers acceptance.
2. Add exact-trigger focus restoration assertions if multiple visible diagnostics controls are introduced per row.
3. Consider splitting v2 routes into dynamic chunks when additional migrated pages increase bundle size.
