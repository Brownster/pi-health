# LimeOS / v2 Hardening - Remediation Tickets

Date: 2026-06-27
Source: `Docs/colleagues_review_of_limeOS.txt` (validated external review)
Branch: TBD (recommend `feature/v2-hardening`)
Status: Draft — not started (v2 under on-Pi testing)

## Objective
Production-harden the migrated v2 / LimeOS stack — close the destructive failure paths and the
security boundary gaps the automated suite does not cover — **before** removing legacy v1 code or
starting broad feature work. IDs match the review for traceability.

## Scope Guardrails
1. No backend API contract changes except where a ticket explicitly requires one (API-001).
2. Every fix lands with a failure-path test (the gap the review highlights).
3. Keep the `legacy|hybrid|v2` rollback path intact until the separate legacy-removal pass.
4. Frontend bundle budget and full `tox -e all` gate stay green.

## Remediation Order (recommended)
1. Quick wins, high impact: **SEC-001**, **UI-001**, **SYS-001**.
2. Privileged-helper contract: **SEC-002**.
3. Destructive backend correctness + failure-path tests: **CAT-001**, **STK-001**, **MFS-001**.
4. SnapRAID fail-closed + cross-plugin preflight: **SRA-001**, **SRA-002**.
5. Concurrency + long-op safety: **STK-002**, **CAT-002**, **API-001**.
6. UI correctness/feedback: **UI-002**, **UI-003**, **UI-006**.
7. Runtime mount dependency safety: **DSK-001** (+ **DSK-002**).
8. Reliability/a11y/config/structure: **STK-003/004/005/006**, **CAT-003**, **UI-004/005**, **CFG-001**, **ARCH-001**.
9. Enhancements (separate scope): **FEATURE-001..004**.

## Execution Order and Dependencies
| ID | Title | Severity | Area | Depends | Status |
|---|---|---|---|---|---|
| SEC-001 | Remove default admin credentials | P0 | backend | — | Pending |
| SEC-002 | Narrow privileged helper contract (no raw file content) | P0 | helper | — | Pending |
| CAT-001 | Catalog remove stops only the selected service | P1 | backend | — | Pending |
| STK-001 | Stack delete requires successful compose down | P1 | backend | — | Pending |
| MFS-001 | MergerFS commands return real success/failure | P1 | plugin | — | Pending |
| SRA-001 | SnapRAID mounted-source preflight, fail closed | P1 | plugin | — | Pending |
| SRA-002 | Reject SnapRAID paths on a MergerFS pool | P1 | plugin | — | Pending |
| CAT-002 | Async catalog install via job/stream + operation id | P1 | backend | API-001 | Pending |
| STK-002 | Per-stack lock + atomic compose/env/restore writes | P1 | backend | — | Pending |
| API-001 | State-changing stream endpoints become POST + CSRF | P1 | backend+ui | — | Pending |
| UI-001 | Modal focus survives typing (stable onClose) | P1 | frontend | — | Pending |
| SYS-001 | `/api/stats` tolerates missing optional disks | P1 | backend+ui | — | Pending |
| STK-003 | Round-trip YAML / managed override files | P2 | backend | — | Pending |
| CAT-003 | Merge all allowed top-level compose sections | P2 | backend | STK-003 | Pending |
| STK-004 | `up -d --remove-orphans` (after review) | P2 | backend | — | Pending |
| STK-005 | Detect duplicate compose filenames | P2 | backend | — | Pending |
| STK-006 | Cache one Docker snapshot for status polling | P2 | backend+ui | — | Pending |
| UI-002 | Preserve server error details in API client | P2 | frontend | — | Pending |
| UI-003 | Surface partial-data warnings (mounts/shares) | P2 | frontend | — | Pending |
| UI-004 | Mobile drawer: focus trap, inert bg, skip link | P2 | frontend | — | Pending |
| UI-005 | Derive service-link scheme (no hardcoded http) | P2 | frontend | — | Pending |
| UI-006 | Catalog stack targeting; (app, stack) install model | P2 | backend+ui | — | Pending |
| DSK-001 | Unmount dependency check + media-mount protection | P1/P2 | backend | — | Pending |
| DSK-002 | Safe fstab filesystem presets (no raw default) | P2 | backend | — | Pending |
| CFG-001 | Relocate runtime state out of the source checkout | P2 | backend | — | Pending |
| ARCH-001 | Split oversized modules during the above fixes | P2 | both | — | Pending |

---

## P0 — Security boundary

### SEC-001 — Remove default admin credentials
Files: `app.py` (credential load ~62-77; bind ~1697-1699), `auth_utils.py`, `tests/test_app.py`.
Tasks: refuse to start without configured credentials (or generate a one-time secret requiring
rotation); store/compare password **hashes** with a constant-time verifier; add login rate
limiting. Tests for missing/default config + lockout.
Acceptance: no usable login exists without explicit configuration; brute force is throttled.

### SEC-002 — Narrow privileged helper contract
Files: `pihealth_helper.py` (~671-721), `setup.sh` (~190-212).
Tasks: move systemd unit + startup-script **templates into the helper**; accept only typed,
validated parameters (never full executable content); add peer-credential checks, request-size
framing, and socket security tests.
Acceptance: web-process compromise cannot write arbitrary privileged file content.

## P1 — Correctness, data safety, availability

### CAT-001 — Catalog remove stops only the selected service
Files: `catalog_manager.py` (~534-550), `stack_manager.py` (~255-256).
Tasks: stop/remove only the target service (not the whole stack); abort the compose edit if the
stop fails. Test a 2+ service stack: removing one leaves the rest running.

### STK-001 — Stack delete requires successful compose down
Files: `stack_manager.py` (~423-446).
Tasks: require a successful `docker compose down` before deleting the directory; surface failure to
the UI; add an explicit, separately confirmed force-delete path. Test the down-fails case.

### MFS-001 — MergerFS commands return real success/failure
Files: `storage_plugins/mergerfs_plugin.py` (~391-413, 451-589).
Tasks: return a real `CommandResult` from each delegated mount/unmount/balance; propagate helper /
non-zero / timeout / missing-binary failures so SSE no longer emits `success: true` on failure.

### SRA-001 — SnapRAID mounted-source preflight (fail closed)
Files: `storage_plugins/snapraid_plugin.py` (~556-565, 785-821).
Tasks: verify every data/content/parity path is a mounted source with expected device identity;
fail closed when diff cannot run; make force override explicit + audited. (Review note: parity-wipe
claim was overstated, but preflight is valid defence in depth.)

### SRA-002 — Reject SnapRAID paths on a MergerFS pool
Files: `storage_plugins/snapraid_plugin.py` (~167-170).
Tasks: cross-check against configured MergerFS mount points; reject any data/parity/content path
equal to or below a pool mount. Test pool-path rejection.

### CAT-002 — Async catalog install (depends API-001)
Files: `catalog_manager.py` (~461-468), `stack_manager.py` (~262-279).
Tasks: split into a config transaction + a job/stream endpoint with an operation id; never re-launch
the same op on stream retry. Acceptance: install does not hold a request worker for ~300s.

### STK-002 — Per-stack lock + atomic writes
Files: `stack_manager.py` (~368-550), `catalog_manager.py` (~120-135).
Tasks: per-stack inter-process lock held across backup/edit/replace and conflicting Docker ops;
atomic writes for compose/env/restore. Test concurrent save/install/action.

### API-001 — State-changing streams become POST + CSRF
Files: `stack_manager.py` (~792-865) and frontend consumers (`stacks-page.tsx` console uses
EventSource/GET; `storage-page.tsx` already uses POST-SSE — reuse that fetch-reader pattern).
Tasks: create ops via POST + CSRF, stream a read-only op resource by id via GET; migrate the stacks
console off GET EventSource.

### UI-001 — Modal focus survives typing
Files: `frontend/src/components/ui/modal-overlay.tsx` (effect dep `[onClose]`, ~20-68).
Root cause: inline `onClose` callers re-run the focus effect each keystroke — affects **catalog
install, storage plugin install, mounts config, share config** modals (text fields lose focus).
Tasks: hold `onClose` in a ref and run focus setup on `[]` (one central fix); OR require stable
callbacks. Add a browser test that **types multiple characters** and asserts focus stays in field
(current tests use `.fill()` and miss this).

### SYS-001 — `/api/stats` tolerates missing optional disks
Files: `app.py` (~393-400). Also unblocks the v2 **dashboard** and **System** page, which both read
`/api/stats`.
Tasks: collect each metric independently; return `null` + a scoped warning when a source (e.g.
`/mnt/backup`) is unavailable instead of 500.

## P2 — Reliability, accessibility, product gaps
- **STK-003** round-trip YAML (or managed override files) — `catalog_manager.py:107-135`.
- **CAT-003** merge all allowed top-level compose sections (configs/secrets) — `catalog_manager.py:431-443`.
- **STK-004** add `--remove-orphans` after reviewing external-service preservation — `stack_manager.py:237-268,748-786`.
- **STK-005** detect duplicate compose filenames; block until resolved — `stack_manager.py:20-60`.
- **STK-006** cache one Docker snapshot for status; prevent overlapping polls — `stack_manager.py:296-305`, `stacks-page.tsx`.
- **UI-002** preserve server error JSON in the client — `frontend/src/lib/api.ts:18-20` (`requestApi`); ripples to all pages' error display.
- **UI-003** partial-data warnings + bounded concurrent fan-out — `mounts-page.tsx:105-123`, `shares-page.tsx:77-94`.
- **UI-004** mobile drawer focus trap / inert background / overscroll / skip-link — `app-shell.tsx`.
- **UI-005** derive service-link scheme from metadata, not hardcoded `http://` — `dashboard-home.tsx`, `containers-page.tsx`.
- **UI-006** catalog `target_stack` + represent installs as `(app, stack)` — `frontend/src/lib/catalog.ts`.
- **DSK-001** unmount dependency check (containers/shares/pools/SnapRAID) + protect media mounts — `disk_manager.py:483-526`.
- **DSK-002** safe filesystem-specific fstab presets (no raw free-form default) — `disk_manager.py:409-447`.
- **CFG-001** relocate runtime state: config `/etc/limeos`, state `/var/lib/limeos`, logs `/var/log/limeos`, secrets in credential storage (+ migration plan) — `app.py:29-39`, `catalog_manager.py:20-25`, `backup_scheduler.py:24-25`.
- **ARCH-001** split oversized modules (`app.py` ~1699 lines; containers/stacks/storage pages >800) **as part of** the above fixes, not a standalone rewrite.

## Enhancements (separate scope, not production-readiness defects)
- FEATURE-001 NFS/CIFS remote-mount plugins.
- FEATURE-002 per-mount journal diagnostics (bounded, allowlisted).
- FEATURE-003 disk prepare/power mgmt (wipe/partition/format/hdparm) — destructive; needs its own design + device allowlist + test rig.
- FEATURE-004 threshold notifications (after safety checks fail closed + persist structured events).

## Do NOT do (rejected/corrected by review)
- Do not add a default `.unionfs/` SnapRAID exclude (mergerfs control file is `.mergerfs`; SnapRAID targets raw branches).
- Do not treat `chattr +i` as a complete runtime-disk-loss fix (defence-in-depth only, after dependency-aware shutdown).
- Do not add `BindsTo=` to the current oneshot startup unit (no `ExecStop`; needs managed per-stack services or a mount-health supervisor).

## Test-quality note
Parity suites assert presence/notices via Playwright `.fill()` (atomic), so interaction-fidelity
bugs (focus/keyboard/debounce) slip through (see UI-001). Add a small typing/keyboard test
convention. The full browser suite also times out under load in CI-like runs; failure-path unit
tests should carry most of the new coverage.
