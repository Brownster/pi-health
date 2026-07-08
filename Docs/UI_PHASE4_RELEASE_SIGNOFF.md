# UI Phase 4 — Pools (SnapRAID + MergerFS) Release Signoff

Date: 2026-07-07
Decision: **GO — pending the target-Pi sync smoke** (see Deferred, item 1)
Tickets: `Docs/UI_PHASE4_POOLS_TICKETS.md`
Precondition: Phase 3 signed off (`Docs/UI_PHASE3_RELEASE_SIGNOFF.md`)

## Scope delivered
SnapRAID and MergerFS are now first-class in the v2 Pools UI: structured at-a-glance state,
guided (no-JSON) configuration with a raw-JSON Advanced fallback, and every command runnable with
parameters, confirmation, and live progress.

| Ticket | Outcome |
|---|---|
| PH4-001 Backend surface: `param_schema`, `kind`, `sync_required`, `config-preview` | ✅ additive; unit-tested |
| PH4-002 Pools tab: SnapRAID + MergerFS status cards (`pools.ts` typed views) | ✅ |
| PH4-003 Parameterized commands + confirm + live progress (`command-runner.tsx`) | ✅ |
| PH4-004 SnapRAID guided config editor (`snapraid-editor.tsx`) | ✅ |
| PH4-005 MergerFS pool editor (`mergerfs-editor.tsx`) | ✅ |
| PH4-006 Schedules + pre-sync safety gate (`snapraid-schedule.tsx`) | ✅ |
| PH4-007 E2E parity + release signoff | ✅ (this doc) |
| Phase 4 review fixes (findings 1–4, 6 + Apply-confirm) | ✅ |

## Additive backend surface (PH4-001)
- `StoragePlugin.PLUGIN_KIND` (`"pool"` for SnapRAID/MergerFS) surfaced as `kind` on list + detail →
  `isPoolPlugin()` prefers the flag, legacy id/category heuristic as fallback.
- SnapRAID: `scrub` `param_schema`; `status.details.sync_required`; `preview_config()`.
- MergerFS: `pool_name` select `param_schema` (sourced from `status.details.pools[].name`); `unmount`
  flagged `dangerous`.
- `POST /api/storage/plugins/<id>/config-preview` (CSRF-gated, no write, 400 on malformed input).
- Contract is additive — pre-existing storage tests pass unchanged.

## Validation matrix (2026-07-07, full `tox -e all` pre-commit gate)
- `npm --prefix frontend run check` (tsc) — pass
- `npm --prefix frontend run build:publish` — pass
- `node scripts/check_frontend_bundle_budget.mjs` — pass (initial JS **108.75 kB gz / 200 kB**, CSS ~6.7 kB)
- Unit suite (`pytest -m 'not e2e'`) — **1024 passed, 1 skipped**
- e2e suite (`pytest -m e2e`) — **103 passed** (storage suite 16, incl. configured-state cards
  across phone/tablet/desktop)
- ruff gate (now `E9,F`) — pass

## e2e coverage added (PH4-007)
- Configured-state cards across phone/tablet/desktop: healthy SnapRAID (protection badge, drive
  counts, last-run summary chips) + MergerFS mounted pool (capacity meter) and degraded/unmounted
  pool, with no horizontal overflow at 390px.
- Guided editors: SnapRAID (assign drives → preview `snapraid.conf` → schedule) and MergerFS
  (add pool → two branches → save → apply-with-confirm).
- Command runner: parameterized run + streamed output; the pre-sync **threshold gate** (Sync aborts
  over `delete_threshold` → counts shown → "Run anyway" retries with `force` → live `run:pos`
  progress from string-valued tags → completion).
- Advanced (JSON) tab still edits/saves raw config for pool + third-party plugins.

## Rollout & rollback
Frontend-only against existing `storage_plugins` blueprints; the backend surface is additive. Rollback
is the standard v2 mechanism (env flags / redeploy the preceding revision); no runtime data change.

## Security posture (carried from the 2026-07-04/05 review)
Every new mutating fetch (command, config, apply, preview) sends `X-CSRF-Token` via `csrfHeaders`;
the app-wide `before_request` enforces it. MergerFS unmount and the fstab-rewriting Apply are
confirm-gated; SnapRAID Apply now is too. Helper `cmd_snapraid` conf/log constraints are respected
(`/etc/snapraid.conf` + `>&1`).

## Deferred / follow-up
1. **Real-hardware sync smoke + the helper 30s-timeout landmine (own ticket).** On the target Pi a
   `sync`/`scrub` longer than ~30s raises `HelperError` in the UI while snapraid keeps running as
   root, and the helper path parses log-tags only after completion — so "live progress" is realised
   on the streaming (dev) path but **not yet verified on production hardware**. Before flipping this
   signoff to unconditional GO, run a real sync on the Pi and confirm progress + no premature
   timeout. The durable fix (per-command timeout, or routing long runs through the streaming path) is
   tracked in `Docs/HELPER_LONGRUN_STREAMING_TICKET.md`.
2. "Suggest layout" for SnapRAID drive roles is a follow-up (new backend; the existing
   `/api/disks/suggested-mounts` does mount placement, not data/parity role assignment).
3. Timer state (enabled/next-run) is not surfaced — the schedule UI is config-driven; a read-only
   status command outside the mutation lock would be needed to poll it (M1).

## Decision
**GO for the v2 Pools feature set**, conditional on the target-Pi sync smoke (Deferred item 1). All
seven tickets and the review fixes are delivered with the evidence above; automated coverage is green
across phone/tablet/desktop.
