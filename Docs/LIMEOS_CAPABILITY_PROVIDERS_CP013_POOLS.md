# LimeOS Capability Providers CP-013 Pools Page

Date: 2026-07-18

Status: Implemented

Scope: CP-013 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

## Domain Ownership

`/pools` is now a capability-owned page rather than the Pools tab of storage plugin
administration. It consumes `storage.pooling` providers and exposes:

- A fleet summary for pool count, mounted state, aggregate capacity, free space, and
  warnings
- One operational card per configured pool
- Enabled but unconfigured providers as setup rows
- Disabled installed providers as available providers, not operational pools
- Administrator-only provider discovery actions
- Stable provider deep links at `/pools/:providerId`

Provider identity remains secondary on pool cards. Cards lead with the pool name, mount
point, health, branches, policy, and capacity.

## Generic Providers

Provider detail routes mount the bounded generic renderer delivered by CP-005. Generic
status summaries, metrics, issues, and recent activity remain owned by LimeOS and do not
load provider JavaScript, HTML, or remote assets.

This slice does not add a new provider execution API. Setup and action catalogs remain
bounded by the existing contracts and will connect as their runtime adapters land.

## Existing MergerFS Installations

The capability registry does not yet discover production storage plugins by default.
Until CP-017 supplies the full migration adapter, the Pools page uses a read-only
MergerFS compatibility adapter when registry data is absent or lacks pool details.

The adapter:

- Reads the existing plugin list and MergerFS detail payload
- Preserves current pool names, mount points, branch counts, capacity, and mount state
- Excludes SnapRAID because protection does not belong to `storage.pooling`
- Adds no polling and performs no privileged helper operation
- Leaves configuration, apply, commands, and recovery available through the existing
  Plugins detail workflow

CP-014 replaces this bridge with the tailored MergerFS renderer. CP-017 then maps the
first-party runtime directly into the capability contracts.

## Failure States

Registry failure falls back to existing MergerFS data and shows a compatibility warning.
If both registry and legacy storage reads fail, the page presents a bounded retry state.
Unknown provider deep links fail closed with a provider-not-found state.

Empty pages remain discoverable. Administrators can open Extensions to install or enable
a pooling provider; authorized non-admin users can inspect provider health without seeing
an installation action.

## Existing-Instance Deployment

No manual migration is required. CP-013 does not change databases, helper commands,
plugin configuration, MergerFS files, mount state, or API request shapes.

Use the normal LimeOS updater and hard reload the Pools page after the service restart.
The committed `static/v2` bundle contains the new route, so the target Pi does not need
npm. Existing MergerFS and SnapRAID editors remain reachable from Plugins during the
additive migration.

## Verification

- Storage and Pools Playwright suite across desktop, tablet, and phone: 17 passed
- Capability registry, capability API, and committed-bundle checks: 74 passed
- Frontend pool, route, capability, extension, and disk contract suites: passed
- TypeScript, Ruff, production build, and `git diff --check`: passed
- Manual Playwright screenshots at 1440x1000 and 390x844: no clipping, overlap,
  horizontal overflow, or console errors observed

The repository-wide commit hook exceeds the current command runner lifetime. CP-020 owns
the complete cross-domain regression gate before release signoff.
