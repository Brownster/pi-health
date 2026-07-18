# LimeOS Capability Providers CP-016 SnapRAID Renderer

Date: 2026-07-18

Status: Implemented

Runtime commit: `477bbfc`

Scope: CP-016 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

## Protection-Owned Workflow

`/protection/snapraid` now owns normal SnapRAID administration. The tailored renderer
uses five bounded views:

- **Overview** shows provider health and the current parity protection set.
- **Configuration** assigns data, parity, and content drives; manages sync and scrub
  schedules; previews `snapraid.conf`; and separates save from apply.
- **Operations** exposes Sync and parameter-bounded Scrub commands.
- **Recovery** loads recovery status, failed drives, damage counts, and declared recovery
  options only when opened.
- **Diagnostics** exposes Status, Diff, and Check commands with the latest operation log.

The legacy Plugins detail remains available during the additive migration, but users no
longer need it for first-party SnapRAID setup or operation.

## Safety Boundaries

Changing an assignment, schedule, scrub percentage, or scrub age marks the editor dirty.
Apply remains disabled until the candidate configuration has been saved. Preview is
read-only, and Apply still requires confirmation before writing `/etc/snapraid.conf`.

Sync always requires explicit confirmation because it updates parity. The existing
pre-sync deletion threshold remains authoritative and still requires a second force
action when exceeded. Fix uses a recovery-specific warning because it can overwrite
damaged files from parity. Provider validation and command execution remain server-side.

Recovery status and operation logs are fetched lazily. The page adds no polling,
background SnapRAID command, or privileged helper call. A transient detail failure during
a silent post-operation refresh keeps the last successful tailored state and reports a
compatibility warning instead of replacing the workflow.

## Access And Compatibility

Administrators can configure SnapRAID and run mutating operations. Read-only overview,
recovery status, diagnostics, and logs remain visible through the existing capability
and action authorization boundaries. Third-party protection providers continue to use
the bounded generic renderer; no provider JavaScript, HTML, or remote asset is loaded.

If the SnapRAID detail endpoint is unavailable on initial load, the page falls back to
the generic status renderer and retains the existing configuration link. Registry
failure continues to use compatibility data from the current SnapRAID plugin.

## Existing-Instance Deployment

No manual migration is required:

- No database, manifest, API, or persisted configuration schema changes are included.
- Existing drive assignments, content files, schedules, thresholds, logs, and plugin IDs
  remain unchanged.
- Updating does not save or apply config and does not run Sync, Scrub, Check, or Fix.
- SnapRAID does not need to be disabled, reinstalled, or reconfigured.
- The committed `static/v2` bundle contains the renderer, so the target Pi does not need
  npm.

Use the normal LimeOS updater and hard reload after the service restart. On Holly, first
compare Overview and Configuration with the recorded assignments and schedules. Run
Status or Diff before considering a parity-writing operation.

## Verification

- Protection Playwright coverage: 7 passed
- Existing storage-parity Playwright regression: 18 passed
- Frontend protection and capability-renderer contract suites: passed
- TypeScript, Ruff lint, production build, bundle freshness, and `git diff --check`:
  passed
- Playwright screenshots at 1440x1000 and 390x844: no clipping, overlap, page overflow,
  or console errors observed

The Vite build reports the existing main-chunk size advisory; it does not fail the build
or affect target-Pi deployment. CP-020 owns the full cross-domain release gate.
