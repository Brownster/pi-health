# UI Phase 3 — Core Management Release Signoff

Date: 2026-06-27
Decision: **GO**
Tickets: `Docs/UI_PHASE3_CORE_MANAGEMENT_TICKETS.md`
Precondition: Phase 2 containers pilot signed off (`Docs/UI_PHASE2_RELEASE_SIGNOFF.md`)

## Scope delivered
All Phase 3 core-management pages migrated to `/v2` with `legacy|hybrid|v2` rollout and instant
per-route rollback, then restyled to the nasOS look & feel.

| Ticket | Outcome |
|---|---|
| PH3-001 Architecture + shared utilities | ✅ shared `lib/api.ts`, route scaffold |
| PH3-002 Stacks read path | ✅ |
| PH3-003a Stacks lifecycle + logs + streaming console | ✅ |
| PH3-003b Stacks compose/env editor + backups/restore | ✅ |
| PH3-004 Disks read path + SMART | ✅ |
| PH3-005 Disks mount/unmount + SMART self-test | ✅ |
| PH3-006a Storage plugins + pools (tabbed) | ✅ |
| PH3-006b Plugin config editor + install wizard | ✅ |
| PH3-007 Mounts (media paths + mounts) | ✅ |
| PH3-007b Mount add/edit + startup-service | ✅ |
| PH3-008 Shares (list + toggle/delete) | ✅ |
| PH3-008b Share add/edit | ✅ |
| PH3-009 Settings (self-update + backups + auto-update) | ✅ |
| PH3-010 Consolidated rollout + parity suite | ✅ |
| PH3-011 Release signoff | ✅ (this doc) |

Live v2 routes: `containers`, `stacks`, `disks`, `plugins`, `pools`, `mounts`, `shares`, `settings`.

## Validation matrix (2026-06-27, full `tox -e all` pre-commit gate)
- `npm --prefix frontend run check` (tsc) — pass
- `npm --prefix frontend run build:publish` — pass
- `node scripts/check_frontend_bundle_budget.mjs` — pass (initial JS **94.08 kB gz / 200 kB**, CSS well under)
- Unit suite (`pytest -m 'not e2e'`) — **558 passed, 1 skipped**
- e2e suite (`pytest -m e2e`) — **151 passed, 27 skipped** (skips are non-applicable mode/viewport combos)
- ruff gate (`E9,F63,F7,F82`) — pass

## Rollout & rollback
- `PIHEALTH_UI_MODE=legacy|hybrid|v2` selects the global mode.
- `PIHEALTH_UI_V2_PAGES=stacks,disks,...` selects which routes serve v2 in `hybrid` mode.
- Per route, `/<page>.html` 302-redirects to `/v2/<page>` only when selected (PH3-010 asserts this
  for all 7 routes); unselected routes serve the legacy page unchanged.
- **Rollback is instant and rebuild-free:** remove the route from `PIHEALTH_UI_V2_PAGES` (or set
  `PIHEALTH_UI_MODE=legacy`). In `legacy` mode `/v2/*` returns 404 and all legacy pages serve.
- Backend API contracts are unchanged across modes (PH3-010 asserts `/api/stacks` parity).

## Backend dependencies unchanged
Phase 3 is frontend-only against existing blueprints (`stack_manager`, `disk_manager`,
`storage_plugins`, `backup_scheduler`, `update_scheduler`, `app.py` pihealth-update). No API
redesign.

## Quality gate
`core.hooksPath` = `scripts/hooks` (pre-commit `tox -e all` active and green on the signoff commit).

## Deferred / follow-up (not blocking Phase 3)
1. nasOS redesign of the remaining v2 routes: **System, Catalog, Network, Tools** (next work item;
   `lib/system.ts` already scaffolded). Tracked in `Docs/UI_V2_NAS_OS_REDESIGN_PLAN.md`.
2. Plugin config + mount/share add-edit use a plugin-agnostic JSON editor (server-validated); a
   per-plugin generated form is a possible future enhancement.

## Decision
**GO.** Phase 3 exit criteria met with evidence above; rollback verified by the PH3-010 rollout
suite and the env-flag procedure.
