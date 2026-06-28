# LimeOS / v2 Hardening - Remediation Tickets

Date: 2026-06-27
Source: `Docs/colleagues_review_of_limeOS.txt` (validated external review)
Branch: TBD (recommend `feature/v2-hardening`)
Status: Active — SEC-001/002, API-001, CAT-001/002, STK-001/002, MFS-001, SRA-001/002, SYS-001, and UI-001/002/003 complete

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
| SEC-001 | Remove default admin credentials | P0 | backend | — | Complete |
| SEC-002 | Narrow privileged helper contract (no raw file content) | P0 | helper | — | Complete |
| CAT-001 | Catalog remove stops only the selected service | P1 | backend | — | Complete |
| STK-001 | Stack delete requires successful compose down | P1 | backend | — | Complete |
| MFS-001 | MergerFS commands return real success/failure | P1 | plugin | — | Complete |
| SRA-001 | SnapRAID mounted-source preflight, fail closed | P1 | plugin | — | Complete |
| SRA-002 | Reject SnapRAID paths on a MergerFS pool | P1 | plugin | — | Complete |
| CAT-002 | Async catalog install via job/stream + operation id | P1 | backend | API-001 | Complete |
| STK-002 | Per-stack lock + atomic compose/env/restore writes | P1 | backend | — | Complete |
| API-001 | State-changing stream endpoints become POST + CSRF | P1 | backend+ui | — | Complete |
| UI-001 | Modal focus survives typing (stable onClose) | P1 | frontend | — | Complete |
| SYS-001 | `/api/stats` tolerates missing optional disks | P1 | backend+ui | — | Complete |
| STK-003 | Round-trip YAML / managed override files | P2 | backend | — | Pending |
| CAT-003 | Merge all allowed top-level compose sections | P2 | backend | STK-003 | Pending |
| STK-004 | `up -d --remove-orphans` (after review) | P2 | backend | — | Pending |
| STK-005 | Detect duplicate compose filenames | P2 | backend | — | Pending |
| STK-006 | Cache one Docker snapshot for status polling | P2 | backend+ui | — | Pending |
| UI-002 | Preserve server error details in API client | P2 | frontend | — | Complete |
| UI-003 | Surface partial-data warnings (mounts/shares) | P2 | frontend | — | Complete |
| UI-004 | Mobile drawer: focus trap, inert bg, skip link | P2 | frontend | — | Pending |
| UI-005 | Derive service-link scheme (no hardcoded http) | P2 | frontend | — | Pending |
| UI-006 | Catalog stack targeting; (app, stack) install model | P2 | backend+ui | — | Complete |
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

Completed: 2026-06-27. Authentication now requires Werkzeug scrypt/PBKDF2 hashes through
`PIHEALTH_PASSWORD_HASH` or `PIHEALTH_USERS`; missing, plaintext, duplicate, and malformed
configuration fails during startup. Password verification uses Werkzeug's constant-time hash
checker, including equivalent hash work for unknown usernames. The login endpoint applies a
per-client five-attempt/60-second lockout and returns `429` with `Retry-After`. Unit coverage
includes missing/default configuration, hashed multi-user loading, lockout, and recovery.
Operator documentation includes a dependency-free hash generator and plaintext-to-hash migration.

### SEC-002 — Narrow privileged helper contract
Files: `pihealth_helper.py` (~671-721), `setup.sh` (~190-212).
Tasks: move systemd unit + startup-script **templates into the helper**; accept only typed,
validated parameters (never full executable content); add peer-credential checks, request-size
framing, and socket security tests.
Acceptance: web-process compromise cannot write arbitrary privileged file content.

Completed: 2026-06-27. Raw `write_systemd_unit` and `write_startup_script` commands were removed
from the helper whitelist. Startup and SnapRAID units now come from fixed helper-owned templates;
callers send only validated mount points, compose paths, job types, and cron values. The Unix-socket
protocol now uses 4-byte length-prefixed request/response frames capped at 64 KiB with a 10-second
read timeout. Linux `SO_PEERCRED` checks require root or actual membership in the `pihealth` process
group before parsing or dispatch, and the runtime directory/socket modes are `0750`/`0660`.

Failure-path coverage rejects removed raw commands, content/path/cron injection, malformed parameter
types, oversized/truncated/timed-out frames, and unauthorized peers; socket modes and typed caller
payloads are asserted. `tox -e all` passed: Ruff clean; unit `590 passed, 1 skipped`; E2E `166 passed,
26 skipped`.

Deployment note: framing is intentionally fail-closed and incompatible with the old helper process.
For this release, rerun `setup.sh` and restart `pihealth-helper.service` and `pi-health.service`
together rather than applying the update through the web UI.

## P1 — Correctness, data safety, availability

### CAT-001 — Catalog remove stops only the selected service
Files: `catalog_manager.py` (~534-550), `stack_manager.py` (~255-256).
Tasks: stop/remove only the target service (not the whole stack); abort the compose edit if the
stop fails. Test a 2+ service stack: removing one leaves the rest running.

Completed: 2026-06-27. Catalog removal now calls service-scoped `docker compose stop <service>`.
Transport and nonzero failures return `409` before backup or compose mutation. Coverage uses a
two-service stack, asserts the exact Compose command, verifies the unrelated service remains in the
file, and verifies stop failure leaves both services and backup state untouched.

### STK-001 — Stack delete requires successful compose down
Files: `stack_manager.py` (~423-446).
Tasks: require a successful `docker compose down` before deleting the directory; surface failure to
the UI; add an explicit, separately confirmed force-delete path. Test the down-fails case.

Completed: 2026-06-27. Stack deletion now requires a successful Compose result. Failure returns
`409` with the command detail and `force_delete_available`, preserving the stack directory and
skipping backup/deletion. Force deletion requires both `force: true` and an exact `confirm_name`;
the legacy stacks UI presents a second destructive confirmation before sending that request.

### MFS-001 — MergerFS commands return real success/failure
Files: `storage_plugins/mergerfs_plugin.py` (~391-413, 451-589).
Tasks: return a real `CommandResult` from each delegated mount/unmount/balance; propagate helper /
non-zero / timeout / missing-binary failures so SSE no longer emits `success: true` on failure.

Completed: 2026-06-27. Mount, unmount, and balance generators now return their actual
`CommandResult`; helper errors, nonzero exits, 60-second mount/unmount timeouts, one-hour balance
timeout, and missing binaries return failure. SSE completion events preserve the underlying `error`.
Affected suites passed `125` tests. Full `tox -e all` passed: Ruff clean; unit `599 passed, 1
skipped`; E2E `166 passed, 26 skipped`.

### SRA-001 — SnapRAID mounted-source preflight (fail closed)
Files: `storage_plugins/snapraid_plugin.py` (~556-565, 785-821).
Tasks: verify every data/content/parity path is a mounted source with expected device identity;
fail closed when diff cannot run; make force override explicit + audited. (Review note: parity-wipe
claim was overstated, but preflight is valid defence in depth.)

Completed: 2026-06-27. SnapRAID configuration now requires a UUID for every drive. Before sync,
the plugin reads `/proc/self/mountinfo`, requires every configured path to be an exact mount point,
and compares its kernel device identity with `/dev/disk/by-uuid/<uuid>`. Missing mounts, unresolved
UUIDs, identity mismatches, unreadable mount data, failed diff commands, and diff timeouts all abort
sync and cannot be forced. Threshold overrides require an explicit reason and are written atomically
to a bounded audit history with the authenticated username before sync can continue.

### SRA-002 — Reject SnapRAID paths on a MergerFS pool
Files: `storage_plugins/snapraid_plugin.py` (~167-170).
Tasks: cross-check against configured MergerFS mount points; reject any data/parity/content path
equal to or below a pool mount. Test pool-path rejection.

Completed: 2026-06-27. SnapRAID validation loads the sibling MergerFS configuration and rejects
paths equal to or below every configured pool mount point, including disabled pools. Malformed or
unreadable MergerFS configuration fails validation closed. Exact-path, descendant-path, disabled-pool,
missing-mount, UUID-mismatch, diff-failure, force-reason, audit-failure, and actor-attribution tests
cover the safety boundary.

Validation: focused storage suites `121 passed`; frontend check and production build passed
(`98.12 kB` initial JS gzip); full `tox -e all` passed with Ruff clean, unit `612 passed, 1 skipped`,
and E2E `166 passed, 26 skipped`.

### CAT-002 — Async catalog install (depends API-001)
Files: `catalog_manager.py` (~461-468), `stack_manager.py` (~262-279).
Tasks: split into a config transaction + a job/stream endpoint with an operation id; never re-launch
the same op on stream retry. Acceptance: install does not hold a request worker for ~300s.

Completed: 2026-06-28. Catalog install validation and the atomic compose update remain a synchronous
transaction under the per-stack lock. When startup is requested, the POST now requires CSRF and
returns `202` with an unguessable operation id and a read-only stream URL immediately after the
configuration is persisted. Docker startup runs once in a background thread; stream replay and
`Last-Event-ID` resume use API-001's bounded, session-owned operation registry and cannot relaunch
the command. Stack and catalog operations share retention machinery but enforce distinct stream
kinds.

Both legacy and v2 catalog clients create the operation and consume its fetch-based SSE stream.
They reject command failures and streams that end without a terminal event; closing the legacy
modal aborts only the listener, not the server operation. Tests cover CSRF, configuration-before-job,
non-blocking creation, replay without relaunch, stream-kind isolation, and thread-start failure after
configuration persistence. Focused verification: backend `96 passed`; catalog + stack Playwright
`13 passed`; TypeScript and production build passed (`98.56 kB` initial JS gzip). Full `tox -e all`:
Ruff clean; unit `630 passed, 1 skipped`; E2E `166 passed, 26 skipped`.

### STK-002 — Per-stack lock + atomic writes
Files: `stack_manager.py` (~368-550), `catalog_manager.py` (~120-135).
Tasks: per-stack inter-process lock held across backup/edit/replace and conflicting Docker ops;
atomic writes for compose/env/restore. Test concurrent save/install/action.

Completed: 2026-06-27. Stack mutations and mutating Compose commands now share a reentrant
per-stack `flock` stored under `.locks`, outside the stack directory so delete/recreate cannot
replace the lock inode. Locks are independent across stacks, serialize threads and processes, and
remain held across catalog read-modify-write transactions, backup, atomic replacement, restore,
delete, synchronous Compose commands, and streamed Compose commands. The lock state resets after a
process fork to prevent inherited reentrancy state from bypassing the kernel lock.

Compose, `.env`, restore, catalog, initial-create, and backup writes now use a shared durable atomic
replacement helper: same-directory temporary file, preserved/explicit permissions, file `fsync`,
`os.replace`, and directory `fsync`. Failure-path tests prove replacement errors preserve original
compose/env/restore content. Deterministic concurrency tests prove an action blocks a simultaneous
save, parallel catalog installs preserve both services, separate processes serialize on one stack,
and different stacks remain independent. Unit verification: `619 passed, 1 skipped`; Ruff and
frontend type checks passed. Full `tox -e all`: Ruff clean; unit `619 passed, 1 skipped`; E2E
`166 passed, 26 skipped`.

### API-001 — State-changing streams become POST + CSRF
Files: `stack_manager.py` (~792-865) and frontend consumers (`stacks-page.tsx` console uses
EventSource/GET; `storage-page.tsx` already uses POST-SSE — reuse that fetch-reader pattern).
Tasks: create ops via POST + CSRF, stream a read-only op resource by id via GET; migrate the stacks
console off GET EventSource.

Completed: 2026-06-28. Login and authenticated session checks now issue a per-session CSRF token.
Stack lifecycle streaming starts only through `POST /api/stacks/<name>/operations` with an exact
`X-CSRF-Token`; the old state-changing GET stream routes are removed. Creation returns `202` with
an unguessable operation id and a read-only stream URL. A single background thread executes each
operation, while stream reads replay buffered events and honor `Last-Event-ID` without launching
Docker again.

Operations are bound to the creating browser session, capped at 100 retained operations and 5,000
events each, and completed operations expire after 15 minutes. Thread-start failure removes the
pending record. Both legacy and v2 stack consoles now use an abortable fetch reader for POST-create
and GET-stream; the v2 duplicate POST fallback is gone. Tests cover missing/invalid CSRF, invalid
actions, session ownership, replay/resume without relaunch, thread-start failure, and retired GET
routes. Focused verification: backend `119 passed, 1 skipped`; v2 Playwright `7 passed`; Ruff,
TypeScript, and production build passed (`98.43 kB` initial JS gzip). Full `tox -e all`: Ruff clean;
unit `627 passed, 1 skipped`; E2E `166 passed, 26 skipped`.

### UI-001 — Modal focus survives typing
Files: `frontend/src/components/ui/modal-overlay.tsx` (effect dep `[onClose]`, ~20-68).
Root cause: inline `onClose` callers re-run the focus effect each keystroke — affects **catalog
install, storage plugin install, mounts config, share config** modals (text fields lose focus).
Tasks: hold `onClose` in a ref and run focus setup on `[]` (one central fix); OR require stable
callbacks. Add a browser test that **types multiple characters** and asserts focus stays in field
(current tests use `.fill()` and miss this).

Completed: 2026-06-27. `ModalOverlay` keeps the latest close callback in a ref while installing its
focus/keyboard lifecycle once per mount. The catalog parity suite now enters a value with sequential
keypresses and asserts both retained focus and the complete typed value.

Validation: `npm --prefix frontend run check` and production build passed (98.12 kB gzip). Full
`tox -e all` passed: Ruff clean; unit `577 passed, 1 skipped`; E2E `166 passed, 26 skipped`. The gate
also corrected the legacy System renderer/test to preserve rollback when an optional disk metric is
`null`.

### SYS-001 — `/api/stats` tolerates missing optional disks
Files: `app.py` (~393-400). Also unblocks the v2 **dashboard** and **System** page, which both read
`/api/stats`.
Tasks: collect each metric independently; return `null` + a scoped warning when a source (e.g.
`/mnt/backup`) is unavailable instead of 500.

Completed: 2026-06-28. Primary and secondary disk usage are collected independently. An unavailable
path leaves only its metric as `null` and adds a structured warning containing `code`, `metric`,
`source`, and `message`; `/api/stats` continues returning HTTP 200 with all healthy CPU, memory,
temperature, network, and disk data. The v2 System page and dashboard surface partial-data warnings
without discarding valid metrics, while the legacy System page renders the same warnings alongside
its existing unavailable-disk state.

Tests cover helper-level independence, the HTTP 200 partial response contract, and v2 warning
visibility with healthy telemetry still rendered. Focused verification: backend `68 passed, 1
skipped`; System Playwright `4 passed`; TypeScript and production build passed (`98.78 kB` initial
JS gzip). Full `tox -e all`: Ruff clean; unit `632 passed, 1 skipped`; E2E `167 passed, 26 skipped`.

## P2 — Reliability, accessibility, product gaps
- **STK-003** round-trip YAML (or managed override files) — `catalog_manager.py:107-135`.
- **CAT-003** merge all allowed top-level compose sections (configs/secrets) — `catalog_manager.py:431-443`.
- **STK-004** add `--remove-orphans` after reviewing external-service preservation — `stack_manager.py:237-268,748-786`.
- **STK-005** detect duplicate compose filenames; block until resolved — `stack_manager.py:20-60`.
- **STK-006** cache one Docker snapshot for status; prevent overlapping polls — `stack_manager.py:296-305`, `stacks-page.tsx`.
- **UI-002** preserve server error JSON in the client — `frontend/src/lib/api.ts:18-20` (`requestApi`); ripples to all pages' error display. **Complete 2026-06-28:** failed responses now become typed `ApiError` instances carrying stable `status`, `code`, `path`, `message`, `details`, and truncation state. The shared client reads at most 64 KiB, limits displayed messages to 2,000 characters, combines distinct `error`/`message` recovery guidance plus string details, preserves plain-text failures, and safely falls back for empty, malformed JSON, HTML, or unreadable bodies. Existing domain clients and page notices inherit the behavior without page-specific error parsing. Disks parity tests cover structured JSON validation guidance and plain-text helper failure; all `10 passed`. TypeScript and production build passed (`99.48 kB` initial JS gzip). Full `tox -e all`: Ruff clean; unit `632 passed, 1 skipped`; E2E `169 passed, 26 skipped`.
- **UI-003** partial-data warnings + bounded concurrent fan-out — `mounts-page.tsx:105-123`, `shares-page.tsx:77-94`. **Complete 2026-06-28:** mounts and shares now fetch provider details through an ordered four-worker settled mapper instead of sequential loops. Unsupported mount providers (`400`) remain intentional skips; missing, failed, or malformed provider responses produce scoped warnings using UI-002's preserved server guidance. Healthy provider cards remain visible, page status changes to `partial data`, stale warnings clear on subsequent loads, and all-provider failure cannot render a false “no plugins configured” state. Mixed healthy/failing provider coverage passes for both pages; focused mounts + shares Playwright `14 passed`. TypeScript and production build passed (`99.86 kB` initial JS gzip). Full `tox -e all`: Ruff clean; unit `632 passed, 1 skipped`; E2E `171 passed, 26 skipped`.
- **UI-004** mobile drawer focus trap / inert background / overscroll / skip-link — `app-shell.tsx`.
- **UI-005** derive service-link scheme from metadata, not hardcoded `http://` — `dashboard-home.tsx`, `containers-page.tsx`.
- **UI-006** catalog `target_stack` + represent installs as `(app, stack)` — `frontend/src/lib/catalog.ts`. **Complete 2026-06-28:** catalog status now returns deterministic, deduplicated stack membership for each service. The v2 catalog preserves those `(app, stack)` installations, loads valid stack targets, defaults dependency-bearing apps to a stack containing all catalog dependencies, and sends explicit `target_stack`/`stack_name` values for every install. Apps can be installed into additional stacks, while each installed stack has its own labeled, confirmed remove action that sends the exact target stack. Existing-stack and named-new-stack install requests plus exact-stack removal are covered by Playwright; catalog parity `7 passed`, including modal overflow checks at desktop, tablet, and phone widths. Catalog status unit coverage `3 passed`; TypeScript and production build passed (`100.56 kB` initial JS gzip). Full `tox -e all`: Ruff clean; unit `633 passed, 1 skipped`; E2E `172 passed, 26 skipped`.
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
