# Phase 4 Pools - SnapRAID + MergerFS Management Tickets (Draft)

Date: 2026-07-05
Reviewed: 2026-07-05 — added CSRF/helper-hardening/concurrency integration notes from the security
review remediation (see "Security posture" below); PH4-001 preview endpoint changed GET->POST for
unsaved-form previews; PH4-004 "Suggest layout" reclassified as new backend (follow-up).
Branch: `feature/ui-phase4-pools` (recommended)
Source: `Docs/snapraid-roadmap.md`, `Docs/mergerfs-roadmap.md` (rebased onto the v2 React UI)
Precondition signoff: `Docs/UI_PHASE3_RELEASE_SIGNOFF.md`

## Objective
Make SnapRAID and MergerFS first-class in the v2 UI: guided configuration (no raw JSON),
at-a-glance state (protection health, last sync/scrub, per-pool mount + capacity), and the
common actions (sync, scrub, diff, fix, mount/unmount/balance) runnable with parameters,
confirmation, and live progress.

## Where we are (2026-07-05 audit)

Backend is largely ready; the gap is v2 UI.

Already working server-side:
- `storage_plugins/snapraid_logtags.py`: log-tag parser; `run_command` accepts
  `stream_tags=True` and yields `{"type": "tag", "name": ..., "values": ...}` events
  (progress, summary counts, errors). Covered by `tests/test_snapraid_logtags.py`.
- `SnapRAIDPlugin.get_status()` details: data/parity drive counts, `last_summary`,
  `last_command`, `last_run_at`, `last_log_path`, plus "Sync required" degraded state.
- `SnapRAIDPlugin.run_command` scrub accepts `percent` / `age_days`; `fix` exists and is
  flagged `dangerous`.
- Schedules: `snapraid` config `schedule.sync_cron` / `schedule.scrub_cron` +
  `apply_schedule()` -> helper `configure_snapraid_schedule` -> systemd timers.
- `MergerFSPlugin.get_status()` details: per-pool `mounted`, `branches`, `used_percent`,
  `total_bytes`/`free_bytes`; commands `mount`/`unmount`/`balance` take `pool_name`.
- JSON Schemas exist for both configs (`config/schemas/snapraid.schema.json`,
  `config/schemas/mergerfs.schema.json`).
- Disk inventory + role suggestions: `disk_inventory_service.py`, `disk_suggestion_service.py`.

v2 UI gaps (all in `frontend/src/pages/storage-page.tsx` + `frontend/src/lib/storage-plugins.ts`):
- Pools tab renders the same generic `PluginCard` as Plugins; detail modal shows a one-line
  status message — none of the structured details above are displayed.
- Config editing is a raw JSON `<textarea>` with the schema listed as plain text.
- Any command declaring `params` is **disabled** (PH3-006a review fix), so MergerFS
  mount/unmount/balance are currently unusable from v2, and scrub can't take options.
- No schedule UI, no pre-sync diff/safety gate, no live progress (raw lines only).

### Security posture (2026-07-04/05 review remediation) — affects this work
- **CSRF is enforced app-wide.** Every authenticated `POST/PUT/PATCH/DELETE` now requires a valid
  `X-CSRF-Token` (a `before_request` in `app.py`). The storage command (`.../commands/<cmd>`) and
  config (`.../config`) POSTs are covered; the current frontend already sends the token because
  `storage-plugins.ts` uses `csrfHeaders`. **Any new or modified mutating fetch must send it too**
  (`...(await csrfHeaders("POST"))` or go through `requestApi`), or it 403s.
- **Helper `cmd_snapraid` is constrained:** `conf_path` must be `/etc/snapraid.conf` or
  `/etc/snapraid-diff.conf`; `log_target` must be `>&1`/`>&2` or a file under the managed snapraid
  log dir. The plugin already uses `/etc/snapraid.conf` + `>&1`, so no change is needed — but new
  code (e.g. the pre-sync diff) must stay within those.
- **Helper serves connections concurrently (M1):** SnapRAID `sync`/`scrub`/`diff` run lock-free, so a
  long run no longer blocks status refreshes or a MergerFS mount check (good for live progress).
  MergerFS `mount`/`unmount`, `fstab_set_section`, and `systemctl` serialize under a mutation lock.

## Scope Guardrails
1. API changes are **additive only** (new fields/params on existing `/api/storage/plugins*`
   contracts); legacy consumers must keep working.
2. Reuse the Phase 2/3 primitives: page shell, cards, modal focus handling, `role=status`
   notices, single-flight `pendingId`, SSE-over-POST command streaming.
3. Preserve the mobile baseline: no horizontal overflow at 390px, touch targets >= 44px.
4. Keep the raw JSON editor available as an "Advanced" fallback for both plugins (and the
   only editor for third-party plugins).
5. Dangerous or destructive actions (`fix`, unmount, apply that rewrites fstab) require an
   explicit confirm step; never run them as a side effect of Save.
6. Bundle budget from PH3 still applies (JS <= 200 kB gz).
7. Every new or modified mutating request (POST/PUT/PATCH/DELETE) must send the session CSRF token
   via `...(await csrfHeaders("POST"))` or by routing through `requestApi`; app-wide enforcement now
   rejects authenticated mutations without a valid `X-CSRF-Token` (403).

## Execution Order and Dependencies
| Order | Ticket | Depends On | Critical Path | Status |
|---|---|---|---|---|
| 1 | PH4-001 Backend surface: command param metadata + typed status | — | Yes | In progress |
| 2 | PH4-002 Pools tab: SnapRAID + MergerFS status cards | PH4-001 | Yes | In progress |
| 3 | PH4-003 Parameterized commands + confirm + live progress | PH4-001 | Yes | In progress |
| 4 | PH4-004 SnapRAID guided config editor | PH4-001 | Yes | In progress |
| 5 | PH4-005 MergerFS pool editor | PH4-001 | Yes | In progress |
| 6 | PH4-006 Schedules + pre-sync safety gate | PH4-003, PH4-004 | No | In progress |
| 7 | PH4-007 E2E parity + release signoff | all | Yes | Planned |

---

## PH4-001 - Backend surface: command param metadata + typed status (P0)
Estimate: 0.5-1 day

Small additive API changes so the UI can be schema-driven instead of hardcoding plugin ids.

### Files
- `storage_plugins/snapraid_plugin.py`
- `storage_plugins/mergerfs_plugin.py`
- `storage_plugins/base.py` (if a shared command-descriptor shape helps)
- `frontend/src/lib/storage-plugins.ts` (types only)
- `tests/test_storage_api.py`, plugin unit tests

### Tasks
1. Extend `get_commands()` param declarations from bare names to descriptors:
   `{"name": "pool_name", "type": "select", "source": "status.details.pools[].name", "required": true}`,
   `{"name": "percent", "type": "number", "min": 0, "max": 100, "default": 8, "required": false}`, etc.
   Keep the old `params: [str]` shape parseable (additive: new key `param_schema`).
2. SnapRAID `get_commands()`: declare optional `percent`/`age_days` on `scrub` (backend
   already honours them); keep `fix` `dangerous: true`.
3. Add a `capabilities` (or `kind: "pool"`) flag to the plugin list payload so
   `isPoolPlugin()` stops guessing from ids.
4. SnapRAID status: add an explicit `details.sync_required: bool` (today the UI would have
   to parse the message string).
5. Add a `POST .../snapraid/config-preview` that accepts a **candidate config body** and returns the
   generated `snapraid.conf` text from `_generate_config` without writing — so the editor can preview
   *unsaved* form state (a GET of the saved config can't do that). As a POST it also needs the CSRF
   token; it must not mutate anything.

### Acceptance Criteria
1. Existing tests pass unchanged (contract is additive).
2. `/api/storage/plugins` and plugin detail expose param schemas, pool capability, and
   `sync_required` and are covered by unit tests.
3. `config-preview` returns generated conf for a candidate config, writes nothing, and is CSRF-gated.

---

## PH4-002 - Pools tab: SnapRAID + MergerFS status cards (P0)
Estimate: 1 day

Replace the generic cards on the Pools tab with pool-aware cards fed entirely by data the
backend already returns.

### Files
- `frontend/src/components/storage/snapraid-card.tsx` (new)
- `frontend/src/components/storage/mergerfs-pool-card.tsx` (new)
- `frontend/src/pages/storage-page.tsx`
- `frontend/src/lib/pools.ts` (new: typed views over plugin detail/status payloads)

### Tasks
1. SnapRAID card: protection state badge (healthy / sync required / error / unconfigured),
   data+parity drive counts, last sync and last scrub with relative age ("2 d ago"), and
   the last run summary counts (added/removed/updated from `last_summary`) when present.
2. MergerFS: one card (or row) per pool from `status.details.pools[]`: name, mount point,
   mounted badge, branch count, capacity meter from `used_percent` (reuse the disks page
   meter styling). Degraded styling when unmounted.
3. Primary actions on the card itself: SnapRAID "Sync" / "Scrub"; MergerFS "Mount"/"Unmount"
   per pool (wired in PH4-003 — render disabled until then if sequencing requires).
4. Keep the existing detail modal reachable ("Details") for recovery/logs/raw commands.

### Acceptance Criteria
1. `/v2/pools` shows structured state with zero additional API calls beyond
   list + per-plugin detail (no polling storms).
2. Unconfigured plugins show a clear "Set up" call-to-action leading to PH4-004/005 editors.
3. Cards are usable at 390px.

---

## PH4-003 - Parameterized commands + confirm + live progress (P0)
Estimate: 1-1.5 days

Unblocks the currently-disabled commands and makes long runs legible.

### Files
- `frontend/src/components/storage/command-runner.tsx` (new: param form + output panel)
- `frontend/src/lib/storage-plugins.ts` (`streamPluginCommand`: pass params, surface `tag` events)
- `frontend/src/pages/storage-page.tsx`
- `storage_plugins/snapraid_plugin.py` (only if `stream_tags` needs to default on for UI calls)

### Tasks
1. Render a small form from PH4-001 param schemas before running a command:
   `pool_name` as a select pre-filled from status details (auto-submit when only one pool),
   scrub `percent`/`age_days` as optional numbers with defaults.
2. Enable the previously disabled parameterized commands; remove the PH3-006a stopgap hint.
3. Dangerous commands (`fix`): confirmation dialog stating what will happen, styled like
   the existing stack delete confirm.
4. Consume `{"type": "tag"}` events from the SSE stream: `run:pos` -> progress bar with
   percent (+ ETA/speed when present); `summary:*` -> completion summary panel;
   `msg:error|fatal` -> inline error emphasis. Fall back to the raw line log for
   everything else (keep the existing `<pre>`).
5. On command completion, refresh the plugin status so cards update (sync_required clears
   after a successful sync).

### Acceptance Criteria
1. MergerFS mount/unmount/balance runnable from v2 with pool selection.
2. Scrub runnable with percent/age options; fix requires explicit confirmation.
3. A sync shows live progress; a completed run shows summary counts without reading logs.
4. Transport failures (helper unavailable/503, CSRF/403, 500) surface distinctly from a command that
   ran and reported a tag-level error — the user can tell "couldn't start" from "ran and failed".

---

## PH4-004 - SnapRAID guided config editor (P0)
Estimate: 1.5-2 days

Replace the JSON textarea (for SnapRAID) with a structured form; keep JSON as Advanced tab.

### Files
- `frontend/src/components/storage/snapraid-editor.tsx` (new)
- `frontend/src/lib/disks.ts` (reuse), `frontend/src/lib/pools.ts`
- `frontend/src/pages/storage-page.tsx`

### Tasks
1. Drive assignment: pick from mounted `/mnt/*` disks via the existing disks inventory API;
   assign role data/parity per drive; show size per drive. A one-click "Suggest layout" is a
   **follow-up, not existing-API wiring**: the only exposed suggestion endpoint today
   (`/api/disks/suggested-mounts`) does mount placement (NVMe/USB), not SnapRAID data/parity role
   assignment — role suggestions need new backend logic and should not be scoped inside this ticket.
2. Client-side validation mirroring the roadmap rules, as inline warnings (server stays
   authoritative via `validate_config`):
   - >= 1 parity, >= 1 data drive;
   - warn when a parity drive is smaller than the largest data drive;
   - recommend content files on multiple disks.
3. Settings/thresholds/scrub sections generated from `config/schemas/snapraid.schema.json`
   with the schema `description` strings as tooltips (nohidden, autosave, blocksize, ...).
4. "Preview snapraid.conf" using the PH4-001 preview endpoint (POST with the candidate config)
   before Apply.
5. Save (`set_config`) and Apply (`apply_config`) as distinct actions with distinct
   feedback, reusing the field-level error details `savePluginConfig` already returns.
6. Advanced tab: the existing raw JSON editor, unchanged, for all plugins.

### Acceptance Criteria
1. A fresh SnapRAID setup (assign drives -> save -> apply) is possible without typing JSON.
2. Validation errors from the server map onto the form fields (not just a toast).
3. Third-party plugins still get the raw editor (no regression).

---

## PH4-005 - MergerFS pool editor (P0)
Estimate: 1-1.5 days

### Files
- `frontend/src/components/storage/mergerfs-editor.tsx` (new)
- `frontend/src/pages/storage-page.tsx`

### Tasks
1. Pools list editor over `config.pools[]`: add/remove pool, name, mount point (default
   `/mnt/<name>`), enabled toggle.
2. Branch picker: choose from mounted disks (same source as PH4-004) plus free-text row for
   globs; enforce `minItems: 2` and distinct paths client-side.
3. `create_policy` select with plain-language descriptions (epmfs default: "existing path,
   most free space"); `min_free_space` input validated as `<N>[MGT]`.
4. Options presets from the roadmap/QuickStart (kernel >= 6.6 vs <= 6.5 + mmap) as a
   dropdown that fills the options string, still editable.
5. Apply flow: show what will change (fstab section rewrite + mounts) and confirm before
   calling apply; refresh pool status after.

### Acceptance Criteria
1. Creating a two-branch pool end-to-end from the UI works without JSON.
2. Per-pool validation errors render at the offending pool/branch row.
3. Disabling a pool and applying removes it from the managed fstab section (existing
   backend behaviour) with a visible warning beforehand.
4. If a mount fails *after* the fstab rewrite, the UI surfaces the partial state (and the fstab
   backup path the helper returns); the helper backs up fstab and writes it via `O_NOFOLLOW`.

---

## PH4-006 - Schedules + pre-sync safety gate (P1)
Estimate: 1 day

### Files
- `frontend/src/components/storage/snapraid-schedule.tsx` (new)
- `frontend/src/pages/storage-page.tsx`
- `storage_plugins/snapraid_plugin.py` (expose timer enabled/next-run state if cheap)

### Tasks
1. Schedule section in the SnapRAID editor: enable + cron for sync and scrub with preset
   choices ("daily 03:00", "weekly Sun 04:00", custom cron string), driving the existing
   `schedule.*` config keys; Apply calls the existing `apply_schedule` path.
2. Show current timer state (enabled + next run) if PH4-001 can expose it from
   `systemctl`; otherwise show configured cron only.
3. Pre-sync gate: the Sync button first runs `diff` (streamed), shows
   added/removed/updated/moved counts from tags, and requires confirmation when removals
   exceed `thresholds` from config (backend `thresholds` schema section already exists).
   Offer "Sync anyway" with the dangerous-action styling.

NOTE (backend constraints): the pre-sync `diff` must run against an allowlisted conf
(`/etc/snapraid.conf` or `/etc/snapraid-diff.conf`) and a `log_target` of `>&1`/`>&2`/the managed
snapraid log dir — the privileged helper now rejects other values. Timer-state reads go through the
helper `systemctl` command, which serializes under the mutation lock (M1); if you poll timer state,
prefer exposing it once via PH4-001 or add a dedicated read-only status command rather than polling.

### Acceptance Criteria
1. Enabling a schedule creates/enables the systemd timers via the existing helper path.
2. A sync that would delete more than the threshold requires explicit confirmation and
   shows the diff counts that triggered it.

---

## PH4-007 - E2E parity + release signoff (P0)
Estimate: 1 day

### Files
- `tests/e2e/test_v2_pools_parity.py` (new)
- e2e mock fixtures (extend `install_v2_storage_api_mocks`)
- `Docs/UI_PHASE4_RELEASE_SIGNOFF.md` (new, at completion)

### Tasks
1. Mock fixtures: SnapRAID healthy / sync-required / unconfigured; MergerFS mounted /
   degraded pools; command SSE streams including `tag` progress + summary events; config
   save with field-level validation errors.
2. E2E: pools cards render state; parameterized command runs with pool select; scrub with
   options; fix confirm; SnapRAID editor save/apply; MergerFS pool create; schedule apply —
   across phone/tablet/desktop viewports.
3. `npm run check`, `build:publish`, bundle budget, full unit + e2e suites green.
4. Write the signoff doc following the PH0-PH3 format.

### Acceptance Criteria
1. New e2e suite green in `tox -e e2e` alongside existing v2 suites.
2. Signoff doc records evidence and any deferred items.

---

## Out of scope (deferred)
- SnapRAID `fix -m`/`-e` recovery filters UI (roadmap §4) — revisit after PH4-003 ships the
  param-form plumbing it needs.
- `pool` (SnapRAID pooling) config option — mergerfs is the recommended path.
- Disk-failure replacement wizard (guided `fix` after swapping a drive) — candidate Phase 5.
- Live `run:pos` thermal/CPU stats display — parser already captures them; card real estate
  decision deferred.
