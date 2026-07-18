# LimeOS Capability Providers CP-014 MergerFS Renderer

Date: 2026-07-18

Status: Implemented

Runtime commit: `e5b0d5b`

Scope: CP-014 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

## Provider Surface

`/pools/mergerfs` now owns normal MergerFS setup and operation. The tailored renderer
uses three bounded views:

- Overview shows provider health, configured pool cards, mounted state, capacity, and
  pool operations.
- Configuration provides the guided branch, policy, preset, free-space, preview, save,
  and apply workflow.
- Diagnostics runs the existing status command and loads the latest provider log only
  when the view is opened.

The legacy Plugins detail remains available during the additive migration. Generic
pooling providers still use the generic capability renderer and do not load provider
frontend code.

## Configuration Safety

The editor treats branch order as configuration and provides stable move and remove
controls. Mounted `/mnt/*` filesystems are offered as candidates, while an administrator
can enter a custom branch path or glob.

Client validation rejects incomplete pool names, fewer than two distinct branches,
unsafe mount points outside `/mnt/`, and malformed minimum-free-space values. Server
validation remains authoritative.

Preview calls the existing bounded `config-preview` API. MergerFS now renders the exact
managed fstab section without writing config, fstab, or mount state. Save must complete
before Apply becomes available. Apply retains the explicit fstab and remount warning.

## Operations And Diagnostics

Mount, unmount, and balance use the provider's declared pool selector. Unmount requires
a resource-specific confirmation because it can interrupt applications using the pool.
Command output continues to use the bounded SSE runner and refreshes provider state after
completion.

Diagnostics remains demand-driven. Opening the page or Overview does not fetch logs or
run a helper command. The latest log is requested only when Diagnostics opens, and live
status runs only when selected.

Configuration and mutating controls are restricted to administrators in the capability
page. Requests retain the existing login, CSRF, validation, and fixed-command behavior.
CP-017 owns the final first-party adapter and capability-policy alignment.

## Existing-Instance Deployment

No manual migration is required:

- No database schema changes are included.
- Existing MergerFS configuration, plugin identifiers, fstab entries, and mount state
  remain valid.
- Updating does not rewrite fstab or remount a pool. Only the administrator's explicit
  Apply action does so.
- MergerFS does not need to be disabled, reinstalled, or reconfigured.
- The committed `static/v2` bundle contains the renderer, so the target Pi does not need
  npm.

Use the normal LimeOS updater, let the service restart, then hard reload the browser.
Verify `/pools/mergerfs` before using Apply on a production pool.

## Verification

- MergerFS and storage API tests: 59 passed
- Storage and Pools Playwright suite: 18 passed
- Frontend pool, capability-renderer, and route contract suites: passed
- TypeScript, Ruff, production build, bundle freshness, and `git diff --check`: passed
- Playwright screenshots at 1440x1000 and 390x844: no clipping, overlap, horizontal
  overflow, or console errors observed

The Vite build reports the existing main-chunk size advisory; it does not fail the build
or change target-Pi deployment. CP-020 owns the full cross-domain release gate.
