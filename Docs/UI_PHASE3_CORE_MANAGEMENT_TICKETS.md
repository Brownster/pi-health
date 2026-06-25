# Phase 3 Core Management - Draft Implementation Tickets

Date: 2026-06-25  
Branch: `feature/ui-phase3-core-management` (recommended)  
Source: `Docs/UI_MODERNIZATION_PLAN_phase2.md` (Phase 3)  
Precondition signoff: `Docs/UI_PHASE2_RELEASE_SIGNOFF.md`

## Objective
Migrate the core management pages to `/v2` with the same rollback model proven by the Phase 2 containers pilot.

## Scope Guardrails
1. Preserve existing backend API contracts:
   - `/api/stacks*`
   - `/api/disks*`
   - `/api/storage/plugins*`
   - `/api/storage/mounts*`
   - `/api/storage/shares*`
   - `/api/backups*`
   - `/api/auto-update*`
   - `/api/pihealth/update*`
2. Keep rollout route-by-route through `PIHEALTH_UI_MODE` and `PIHEALTH_UI_V2_PAGES`.
3. Preserve the Phase 0/2 mobile baseline: no horizontal overflow at 390px, touch targets >= 44px, no hover-only controls.
4. Reuse Phase 2 primitives where practical: auth guard, page shell, card/table responsive patterns, modal focus handling, action notices, and v2 e2e fixtures.
5. Do not remove legacy pages during Phase 3. Each migrated route keeps legacy fallback until signoff.

## Execution Order and Dependencies
| Order | Ticket | Depends On | Critical Path | Status |
|---|---|---|---|---|
| 1 | PH3-001 Phase 3 Architecture + Shared Utilities | PH2-008 | Yes | Complete (2026-06-25) |
| 2 | PH3-002 v2 Stacks Read Path + Responsive Layout | PH3-001 | Yes | Complete (2026-06-25) |
| 3a | PH3-003a Stacks Lifecycle + Logs + Streaming Console | PH3-002 | Yes | Complete (2026-06-25) |
| 3b | PH3-003b Stacks Compose/Env Editor + Backups/Restore | PH3-003a | Yes | Complete (2026-06-25) |
| 4 | PH3-004 v2 Disks Read Path + SMART Views | PH3-001 | Yes | Complete (2026-06-25) |
| 5 | PH3-005 Disks Mount/Unmount + SMART Actions | PH3-004 | Yes | Draft |
| 6 | PH3-006 v2 Storage Plugins + Pools | PH3-001 | Yes | Draft |
| 7 | PH3-007 v2 Mounts Management | PH3-006 | Yes | Draft |
| 8 | PH3-008 v2 Shares Management | PH3-006 | Yes | Draft |
| 9 | PH3-009 v2 Settings + Backup/Update Workflows | PH3-001 | Yes | Draft |
| 10 | PH3-010 Phase 3 Parity and Rollout Suite | PH3-002..PH3-009 | Yes | Draft |
| 11 | PH3-011 Phase 3 Release Signoff | PH3-010 | Yes | Draft |

## PH3-001 - Phase 3 Architecture + Shared Utilities (P0)
Owner: Pi-Health maintainers  
Estimate: 1.0 day

### Files
- `frontend/src/app/routes.tsx`
- `frontend/src/lib/api.ts` (new or extend existing helpers)
- `frontend/src/lib/format.ts`
- `frontend/src/components/*` (shared action notice/modal/table helpers if needed)
- `tests/e2e/conftest.py`

### Tasks
1. Define shared API request helpers for Phase 3 pages.
2. Extract reusable responsive table/card and modal patterns only where Phase 2 code proves duplication.
3. Add placeholder route entries for Phase 3 pages behind auth.
4. Extend e2e fixtures so each Phase 3 page can test `legacy|hybrid|v2` routing consistently.
5. Keep bundle budget visible before adding feature pages.

### Acceptance Criteria
1. `/v2/stacks`, `/v2/disks`, `/v2/pools`, `/v2/mounts`, `/v2/shares`, `/v2/plugins`, and `/v2/settings` route through the v2 shell for authenticated users.
2. Legacy routes still serve legacy pages unless selected through `PIHEALTH_UI_V2_PAGES`.
3. Shared helpers do not change Phase 2 containers behavior.
4. `npm --prefix frontend run check` and existing v2 e2e suites pass.

### Status
Complete (2026-06-25)

### Evidence
1. Shared request/normalize helpers extracted to `frontend/src/lib/api.ts`
   (`requestApi`, `toNullableNumber`, `toNullableString`); `lib/containers.ts` and
   `lib/stacks.ts` now import them instead of re-declaring local copies (dedupe).
2. Reusable `createComingSoonPage({ title, legacyHref })` factory
   (`frontend/src/pages/coming-soon-page.tsx`) renders an auth-guarded placeholder in the
   v2 shell with a "Open Legacy <page>" fallback control.
3. Placeholder routes added in `frontend/src/app/routes.tsx` for `disks, pools, mounts,
   shares, plugins, settings` (requiresAuth, `showInNav: false` until each ticket lands).
4. e2e scaffold lock: `tests/e2e/test_v2_phase3_routes.py` asserts each placeholder route
   renders in the v2 shell for authenticated users and redirects to login when unauthenticated
   (reuses the shared `v2_mode_server` / `v2_login` fixtures).
5. Validation:
   - `npm --prefix frontend run check` -> pass
   - `npm --prefix frontend run build:publish` -> pass
   - `node scripts/check_frontend_bundle_budget.mjs` -> pass (initial JS gzip 75.20 kB / 200 kB)
   - `pytest tests/e2e/test_v2_phase3_routes.py tests/e2e/test_v2_foundation.py -q`
     -> `37 passed, 6 skipped` (Phase 2 containers behavior unchanged)

Note: this ticket was backfilled after the stacks read path (PH3-002) was built first; the
shared `lib/api.ts` retro-deduped the request helper that the stacks client had copied.

## PH3-002 - v2 Stacks Read Path + Responsive Layout (P0)
Owner: Pi-Health maintainers  
Estimate: 1.0 day

### Files
- `frontend/src/pages/stacks-page.tsx` (new)
- `frontend/src/lib/stacks.ts` (new)
- `frontend/src/app/routes.tsx`
- `tests/e2e/test_v2_stacks_parity.py` (new or seed)

### Tasks
1. Render stack list from `/api/stacks?status=true`.
2. Show stack name, service count/status, compose file presence, and last-known action state.
3. Add responsive desktop table and phone/tablet cards.
4. Add refresh and empty/error states.
5. Keep lifecycle controls visible but defer complex actions to PH3-003 if needed.

### Acceptance Criteria
1. `/v2/stacks` shows stack rows/cards for authenticated users.
2. Desktop, phone, and tablet views have no horizontal overflow.
3. Legacy `/stacks.html` remains unchanged unless `PIHEALTH_UI_V2_PAGES=stacks`.
4. `/api/stacks?status=true` contract is unchanged.

### Status
Complete (2026-06-25)

### Evidence
1. `frontend/src/lib/stacks.ts`: typed `fetchStacks({ includeStatus })` against
   `GET /api/stacks?status=true` with null-safe `normalizeStack` and a `getStackServicesPercent`
   helper; surfaces the list endpoint's `error` field. Uses shared `lib/api.ts` helpers.
2. `frontend/src/pages/stacks-page.tsx`: stack cards (status badge, running/container services-up
   bar, compose filename), loading/empty/error states, 10s polling with `isMountedRef` cleanup,
   refresh + "last updated".
3. Route + auto-wired shell nav entry (`/stacks`, requiresAuth) in `frontend/src/app/routes.tsx`.
4. Validation: `npm run check` / `build:publish` / bundle budget pass; foundation e2e
   `30 passed, 6 skipped`.
5. Read-path e2e coverage now lives in `tests/e2e/test_v2_stacks_parity.py::test_v2_stacks_list_renders`
   (added with PH3-003a): renders `/v2/stacks`, asserts the stack card + "2 / 2 services up",
   and checks no horizontal overflow across desktop/phone/tablet, backed by an `/api/stacks` mock.

Deviation from task spec: the read path uses a responsive **card grid at all breakpoints**
rather than a desktop table + mobile cards. Stacks have few columns (name/status/services-up) and
this matches the planned nasOS stacks screen; revisit if a denser desktop table is preferred.

## PH3-003 - Stacks Lifecycle, Logs, Editor, and Backups (P0)
Owner: Pi-Health maintainers  
Estimate: 2.0 days

> Split per review-question Q3 into **PH3-003a** (lifecycle + logs + streaming console) and
> **PH3-003b** (compose/env editor + backups/restore), to isolate the higher-risk editor work.
>
> ### PH3-003a Status: Complete (2026-06-25)
> Evidence:
> 1. `frontend/src/components/ui/modal-overlay.tsx` (new): the Phase 2 `ModalOverlay`
>    (focus trap + scroll lock + StrictMode-safe focus restore) extracted for reuse;
>    `containers-page.tsx` now imports it instead of a local copy.
> 2. `frontend/src/lib/stacks.ts`: `runStackAction` (POST), `fetchStackLogs`, and
>    `getStackStreamUrl` for the SSE endpoints.
> 3. `frontend/src/pages/stacks-page.tsx`: per-stack `up/down/restart/pull` controls with
>    in-flight locking; a **streaming action console** that consumes
>    `GET /api/stacks/<name>/<action>/stream` via `EventSource` (line/done/error events),
>    falls back to the `POST` action when the stream errors before completion, and closes
>    the connection on done/close/unmount; a logs modal wired to `/api/stacks/<name>/logs`;
>    `role=status` action notices.
> 4. `tests/e2e/conftest.py`: `install_v2_stacks_api_mocks` fixture (list, action POST,
>    SSE stream body, logs). `tests/e2e/test_v2_stacks_parity.py` (new): list render +
>    overflow matrix, logs modal, and the streaming-console happy path.
> 5. Validation: `npm run check` / `build:publish` / bundle budget (JS 76.74 kB gz / 200 kB) pass;
>    `pytest tests/e2e/test_v2_stacks_parity.py -q` -> `5 passed`.
>
> ### PH3-003b Status: Complete (2026-06-25)
> Evidence:
> 1. `frontend/src/lib/stacks.ts`: `fetchStackCompose`/`saveStackCompose`,
>    `fetchStackEnv`/`saveStackEnv`, `fetchStackBackups`, `restoreStackBackup`.
> 2. `frontend/src/pages/stacks-page.tsx`: per-stack **Edit** modal with Compose/Env tabs
>    (textarea editors, Save with server validation-error surfacing via a `role=status`
>    region) and a **Backups** modal listing backups with a two-step (Restore -> Confirm)
>    keyboard-safe restore; both reuse the shared `ModalOverlay`. Successful restore refreshes
>    the stack list.
> 3. e2e: `install_v2_stacks_api_mocks` extended (compose/env GET+POST, backups GET, restore
>    POST); `test_v2_stacks_parity.py` adds editor (load/edit/save/tab-switch) and
>    backups-restore-with-confirm coverage.
> 4. Validation: `npm run check` / `build:publish` / bundle budget (JS 78.30 kB gz / 200 kB) pass;
>    `pytest tests/e2e/test_v2_stacks_parity.py -q` -> `7 passed`; full v2 e2e set
>    `56 passed, 6 skipped`.

### Files
- `frontend/src/pages/stacks-page.tsx`
- `frontend/src/lib/stacks.ts`
- `tests/e2e/test_v2_stacks_parity.py`

### Tasks
1. Wire `up`, `down`, `restart`, and `pull` actions to existing `/api/stacks/<name>/<action>` endpoints.
2. Support streaming action output from `/api/stacks/<name>/<action>/stream`.
3. Add compose and env editors backed by `/api/stacks/<name>/compose` and `/api/stacks/<name>/env`.
4. Add logs modal backed by `/api/stacks/<name>/logs`.
5. Add backup list, backup preview/download, and restore workflows.

### Acceptance Criteria
1. Core stack actions are reachable on desktop, phone, and tablet.
2. Streaming output, logs, compose editor, and env editor remain keyboard accessible.
3. Per-stack actions prevent duplicate submissions while in flight.
4. E2E mocks cover lifecycle, logs, editor save, and restore confirmation paths.

## PH3-004 - v2 Disks Read Path + SMART Views (P0)
Owner: Pi-Health maintainers  
Estimate: 1.0 day

### Files
- `frontend/src/pages/disks-page.tsx` (new)
- `frontend/src/lib/disks.ts` (new)
- `frontend/src/app/routes.tsx`
- `tests/e2e/test_v2_disks_parity.py` (new or seed)

### Tasks
1. Render disk inventory from `/api/disks`.
2. Render helper status from `/api/disks/helper-status`.
3. Render SMART summary from `/api/disks/smart`.
4. Add responsive table/card layout for disks and partitions.
5. Add SMART detail modal backed by `/api/disks/<device>/smart`.

### Acceptance Criteria
1. `/v2/disks` shows disk inventory and helper status for authenticated users.
2. SMART health data is readable on phone and tablet.
3. No horizontal overflow at 390x844 and 768x1024.
4. Legacy `/disks.html` remains available unless selected for v2 rollout.

### Status
Complete (2026-06-25)

### Evidence
1. `frontend/src/lib/disks.ts`: typed `fetchDiskInventory`, `fetchHelperStatus`,
   `fetchSmartSummary` (keyed by device path), `fetchDiskSmart`; null-safe normalizers using
   shared `lib/api.ts`.
2. `frontend/src/pages/disks-page.tsx`: responsive disk-card grid (device/model, size, bus,
   partitions with fs/mount/size), a SMART health badge per disk merged from the SMART summary,
   a helper-unavailable warning banner, loading/empty/error states, manual refresh + "last
   updated", and a SMART detail modal (`/api/disks/<device>/smart`) reusing `ModalOverlay`.
3. `/disks` promoted from placeholder to a real protected route in `routes.tsx` (in nav);
   removed from the placeholder route test.
4. e2e: `install_v2_disks_api_mocks` fixture (inventory, helper-status, SMART summary + device);
   `tests/e2e/test_v2_disks_parity.py` (inventory + overflow matrix, SMART modal).
5. Validation: `npm run check` / `build:publish` / bundle budget (JS 80.50 kB gz / 200 kB) pass;
   `pytest test_v2_disks_parity.py test_v2_phase3_routes.py -q` -> `10 passed`; full v2 set
   `59 passed, 6 skipped`.

Deferred to PH3-005: mount/unmount, suggested mounts, and SMART self-test actions.

Deviation from task spec ("responsive table/card layout"): the disks view uses a responsive
**card grid at all breakpoints** rather than a desktop table + mobile cards. Each disk's
partitions are naturally nested under its card (variable count, fs/mount/size/uuid per row),
which reads better than a flat table; this matches the card approach taken for stacks. Revisit
if a denser desktop table is preferred.

## PH3-005 - Disks Mount/Unmount + SMART Actions (P0)
Owner: Pi-Health maintainers  
Estimate: 1.5 days

### Files
- `frontend/src/pages/disks-page.tsx`
- `frontend/src/lib/disks.ts`
- `tests/e2e/test_v2_disks_parity.py`

### Tasks
1. Add suggested mount workflow from `/api/disks/suggested-mounts`.
2. Wire mount and unmount actions to `/api/disks/mount` and `/api/disks/unmount`.
3. Add SMART self-test action through `/api/disks/<device>/smart-test`.
4. Add confirmation dialogs for destructive or system-changing actions.
5. Preserve helper-unavailable and permission-warning states.

### Acceptance Criteria
1. Mount/unmount controls are reachable without hover.
2. Confirmation dialogs trap focus and restore focus to the trigger.
3. Success/error feedback is announced through live regions.
4. E2E mocks cover mount, unmount, SMART test, and helper-unavailable states.

## PH3-006 - v2 Storage Plugins + Pools (P0)
Owner: Pi-Health maintainers  
Estimate: 1.5 days

### Files
- `frontend/src/pages/plugins-page.tsx` (new)
- `frontend/src/pages/pools-page.tsx` (new)
- `frontend/src/lib/storage-plugins.ts` (new)
- `frontend/src/app/routes.tsx`
- `tests/e2e/test_v2_storage_plugins_parity.py` (new or seed)

### Tasks
1. Render plugin list from `/api/storage/plugins`.
2. Add plugin enable/disable, install, and remove flows.
3. Render pool-capable plugin details, config forms, recovery status, and latest logs.
4. Wire plugin command execution through `/api/storage/plugins/<id>/commands/<command>`.
5. Keep plugin-specific forms schema-driven where possible.

### Acceptance Criteria
1. `/v2/plugins` and `/v2/pools` render plugin data for authenticated users.
2. Enable/disable/install/remove/config flows use existing API contracts.
3. Plugin command output is usable on phone and tablet.
4. E2E mocks cover at least one local storage plugin and one disabled/unavailable state.

## PH3-007 - v2 Mounts Management (P0)
Owner: Pi-Health maintainers  
Estimate: 1.5 days

### Files
- `frontend/src/pages/mounts-page.tsx` (new)
- `frontend/src/lib/mounts.ts` (new)
- `frontend/src/app/routes.tsx`
- `tests/e2e/test_v2_mounts_parity.py` (new or seed)

### Tasks
1. Render media paths from `/api/disks/media-paths`.
2. Support media path save through `/api/disks/media-paths`.
3. Render startup service preview and apply flow.
4. Render remote/local mount plugins and configured mounts.
5. Wire mount, unmount, delete, detect, add, and edit flows through `/api/storage/mounts*`.

### Acceptance Criteria
1. `/v2/mounts` exposes media paths, startup service, and plugin mounts.
2. Mount actions are reachable on phone and tablet.
3. Secret/password fields are not echoed after save unless the API already returns them.
4. E2E mocks cover media paths, startup preview, mount/unmount, and add/edit modal flows.

## PH3-008 - v2 Shares Management (P0)
Owner: Pi-Health maintainers  
Estimate: 1.0 day

### Files
- `frontend/src/pages/shares-page.tsx` (new)
- `frontend/src/lib/shares.ts` (new)
- `frontend/src/app/routes.tsx`
- `tests/e2e/test_v2_shares_parity.py` (new or seed)

### Tasks
1. Render share-capable plugins from `/api/storage/plugins`.
2. Render shares from `/api/storage/shares/<plugin>`.
3. Add create, edit, toggle, delete, and plugin command flows.
4. Add confirmation dialogs for delete operations.
5. Preserve plugin-unavailable and empty states.

### Acceptance Criteria
1. `/v2/shares` renders share list/cards for authenticated users.
2. Create/edit/toggle/delete flows call existing endpoints.
3. Delete confirmation is keyboard safe.
4. E2E mocks cover share CRUD and one plugin command path.

## PH3-009 - v2 Settings + Backup/Update Workflows (P0)
Owner: Pi-Health maintainers  
Estimate: 1.5 days

### Files
- `frontend/src/pages/settings-page.tsx` (new)
- `frontend/src/lib/settings.ts` (new)
- `frontend/src/app/routes.tsx`
- `tests/e2e/test_v2_settings_parity.py` (new or seed)

### Tasks
1. Render Pi-Health update config from `/api/pihealth/update/config`.
2. Support Pi-Health update trigger through `/api/pihealth/update`.
3. Render backup config/status/list and restore flows from `/api/backups*`.
4. Render auto-update config/status/logs and run-now flow from `/api/auto-update*`.
5. Keep long forms readable and usable on phone/tablet.

### Acceptance Criteria
1. `/v2/settings` covers Pi-Health update, backups, and auto-update workflows.
2. Save/restore/run-now actions show clear success/error feedback.
3. Restore actions require confirmation.
4. E2E mocks cover backup config save, backup restore confirmation, auto-update config save, and Pi-Health update trigger.

## PH3-010 - Phase 3 Parity and Rollout Suite (P0)
Owner: Pi-Health maintainers  
Estimate: 1.0 day

### Files
- `tests/e2e/test_v2_phase3_rollout.py` (new)
- `tests/e2e/test_v2_*_parity.py`
- `tests/e2e/conftest.py`

### Tasks
1. Add route-mode assertions for every Phase 3 route in `legacy|hybrid|v2`.
2. Add rollback assertions for each page group.
3. Add no-overflow assertions for desktop, phone, and tablet.
4. Add API contract checks for representative endpoints across UI modes.
5. Keep deterministic mocks for actions that would mutate host state.

### Acceptance Criteria
1. Phase 3 routes redirect only when selected in `PIHEALTH_UI_V2_PAGES`.
2. `legacy` rollback restores every legacy page without rebuild.
3. Critical workflows pass on phone and tablet.
4. `tox -e all` passes with Phase 3 tests included.

## PH3-011 - Phase 3 Release Signoff (P0)
Owner: Pi-Health maintainers  
Estimate: 0.5 day

### Files
- `Docs/UI_PHASE3_RELEASE_SIGNOFF.md` (new)
- `Docs/UI_PHASE3_CORE_MANAGEMENT_TICKETS.md`

### Tasks
1. Run targeted validation matrix: frontend build, bundle budget, unit tests, v2 Phase 3 e2e, and full `tox -e all`.
2. Record go/no-go decision with evidence.
3. Document route-level rollout settings and rollback procedure.
4. Record deferred follow-ups for Phase 4.

### Acceptance Criteria
1. Phase 3 exit criteria are documented with command output.
2. Rollback procedure is tested and recorded.
3. `core.hooksPath` points to `scripts/hooks` before signoff commit.

## Review Questions — Decisions (2026-06-25)
1. **Settings ordering:** keep `settings` **last**. Backup/update/auto-update workflows are
   high-impact and benefit from the patterns hardened on the storage pages first.
2. **Plugins vs pools:** share **one storage surface with tabs** rather than two separate
   routes/pages, since both are driven by `/api/storage/plugins*`. (Routes `/v2/plugins` and
   `/v2/pools` may both resolve into the tabbed surface.)
3. **Split stacks tickets:** **yes** — PH3-003 should be split so the compose/env **editor** work
   is isolated from **lifecycle + logs** work (editors carry more risk and review surface).
4. **First production rollout after `containers`:** **`stacks`** (confirmed with maintainer).

### Reconciliation note
This document is the **single source of truth** for Phase 3. The earlier improvised
`UI_PHASE3_STACKS_TICKETS.md` (stacks-only, conflicting numbering) was retired in favor of this
plan. The stacks read path originally committed as "PH3-001" under that doc is re-mapped to
**PH3-002** here; the shared-utilities work is **PH3-001** (backfilled).
