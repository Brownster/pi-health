# LimeOS Capability Providers CP-015 Protection Page

Date: 2026-07-18

Status: Implemented

Runtime commit: `7b2cf1d`

Scope: CP-015 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

## Domain Ownership

`/protection` now owns provider-neutral storage protection status. The page exposes:

- A summary for protection sets, protected targets, unprotected targets, latest run, and
  next reported run
- One operational card per provider-reported protection set
- Required-action and provider-health warnings at a glance
- Enabled but unconfigured providers as setup rows
- Disabled installed providers as available providers
- Stable provider deep links at `/protection/:providerId`
- Administrator-only provider discovery and configuration links

Protection is separate from Pools. SnapRAID is not shown as a pooling provider, and
MergerFS is not shown as a protection set.

## Provider Contract

The page normalizes provider status from `details.protection_sets`. A protection set can
report its type, protected and unprotected target counts, parity or copy count, last run,
next run, schedule, health, and required action.

Counts remain conservative. When a provider does not report unprotected targets, the UI
shows `Not reported` rather than inferring protection from disk inventory. The page adds
no polling, helper call, or background status command.

Generic provider deep links use the bounded generic capability renderer. No provider
JavaScript, HTML, or remote asset is loaded.

## Existing SnapRAID Installations

Until CP-017 supplies the full first-party adapter, a read-only compatibility adapter
maps the current SnapRAID plugin payload into `storage.protection`:

- Data-drive and parity-drive counts become protected and parity targets.
- Current health and `sync_required` become protection health and required action.
- Last command time and the configured schedule are preserved when reported.
- Missing plugin detail produces provider status without inventing a zero-drive set.
- Existing setup, apply, sync, scrub, recovery, and diagnostics remain available through
  Plugins until the CP-016 tailored renderer lands.

## Failure And Empty States

If the capability registry is unavailable, existing SnapRAID data remains visible with a
compatibility warning. If both registry and storage-plugin reads fail, the page shows a
bounded retry state. Unknown provider deep links fail closed.

An empty Protection page remains discoverable in primary navigation. Administrators can
open Extensions to add a provider; non-admin users can inspect available status without
seeing lifecycle actions.

## Existing-Instance Deployment

No manual migration is required:

- No database, manifest, or persisted configuration schema changes are included.
- Existing SnapRAID config, drive assignments, schedules, state, logs, and plugin IDs
  remain unchanged.
- Updating does not apply config, run sync or scrub, or change systemd timers.
- SnapRAID does not need to be disabled, reinstalled, or reconfigured.
- The committed `static/v2` bundle contains the new routes, so the target Pi does not
  need npm.

Use the normal LimeOS updater and hard reload after the service restart. Verify the
Protection summary against the existing SnapRAID status before CP-016 changes any
operational workflow.

## Verification

- Focused Protection Playwright coverage: 6 passed
- Combined Protection and existing storage Playwright regression: 24 passed
- Frontend protection, Pools, capability-renderer, route, and disk contract suites:
  passed
- TypeScript, Ruff, production build, bundle freshness, and `git diff --check`: passed
- Playwright screenshots at 1440x1000 and 390x844: no clipping, overlap, horizontal
  overflow, or console errors observed

The Vite build reports the existing main-chunk size advisory; it does not fail the build
or affect target-Pi deployment. CP-020 owns the full cross-domain release gate.
