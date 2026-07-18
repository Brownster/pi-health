# LimeOS Capability Providers CP-011 Disk Cards

Date: 2026-07-18

Status: Implemented

Scope: CP-011 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

## Page Structure

The Disks page now presents physical storage in three scan levels:

1. A fleet summary shows health, mount state, mounted capacity, and provider allocation.
2. Device cards show model, bus, size, health, temperature, mounted usage, and provider
   ownership.
3. Partition rows show filesystem, mount point, size, usage, and free capacity.

Warning, failing, unknown, unmounted, full, and unused states remain visible without
opening a modal. Provider assignments link to the current Pools surface. The CP-013 and
CP-015 domain pages can replace those compatibility links when their canonical routes
ship.

## Actions

SMART remains a dedicated shield action on each device because it is a common diagnostic.
Mounted filesystems move into the shared accessible overflow menu used by Containers and
Stacks. Selecting `Unmount` opens an explicit inline confirmation before the existing API
request runs.

This slice does not change mount, unmount, SMART detail, or SMART self-test APIs. Suggested
mounts retain their existing workflow for CP-012 hardening.

## Loading and Performance

`GET /api/disks` now includes an additive `summary` property. The summary service composes
this embedded view from the inventory already fetched for the request and reads provider
assignment files without executing provider code. It skips SMART during this critical
path.

The page renders inventory and assignments first. Its existing background SMART request
then merges health and temperature into the summary and device cards. This design adds no
second inventory scan, privileged helper command, continuous polling, cache, background
job, or database.

The standalone authenticated `GET /api/disks/summary` endpoint remains unchanged and still
returns a complete point-in-time summary for other clients.

## Existing-Instance Deployment

No manual migration is required:

1. Use the normal LimeOS update workflow.
2. Let the updater restart the application and helper services.
3. Hard reload the Disks page after the restart.
4. Confirm health, mounted capacity, partition usage, and provider assignments appear.
5. Open SMART for one device and confirm one unmount action reaches its confirmation step.

The update does not rewrite disk, mount, MergerFS, SnapRAID, or database configuration.
The committed production bundle means the target Pi does not need npm.

## Verification

- Disk summary, API, and manager tests: 87 passed
- Frontend disk summary tests: 3 passed
- Disk browser parity suite at desktop and phone widths: 10 passed
- TypeScript, Ruff, production build, bundle freshness, and `git diff --check`: passed
- Manual Playwright screenshots at 1440x1000 and 390x844: no clipping, overlap, or
  horizontal overflow observed

The complete repository suite was not recorded in this slice because the current command
runner terminates commands after roughly 15 seconds. CP-020 retains ownership of the full
cross-domain regression gate.
