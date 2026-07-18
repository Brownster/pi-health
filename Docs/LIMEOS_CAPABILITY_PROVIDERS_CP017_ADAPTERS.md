# LimeOS Capability Providers CP-017 Migration Adapters

Date: 2026-07-18

Status: Implemented

Runtime commit: `b8bc9d7`

Scope: CP-017 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

## Registry Ownership

The backend capability registry now discovers the built-in MergerFS and SnapRAID
providers during normal production startup. Server-owned manifests declare:

- MergerFS as the tailored `storage.pooling` provider for Pools
- SnapRAID as the tailored `storage.protection` provider for Protection
- Existing read, diagnostic, mutation, and destructive actions with fixed parameters,
  permissions, timeouts, and confirmations
- The current built-in Python runtime identity and capability API compatibility

The manifests are declarative. They do not load provider frontend code or expand the
privileged command allowlist.

## Read-Only Legacy Mapping

`LegacyStorageCapabilityAdapter` maps the current plugin payloads into the versioned
capability status contract:

- Existing plugin enablement becomes provider lifecycle enablement.
- Existing config determines configured state without changing the config schema.
- MergerFS pool status preserves name, mount point, branch count, capacity, free space,
  create policy, mount state, and health.
- SnapRAID status preserves data/parity counts, sync requirement, latest run metadata,
  schedule, health, and the parity protection set.
- Missing binaries remain discoverable as unavailable providers.
- Disabled providers remain discoverable without running their status reader.
- A corrupt or failing provider is isolated and cannot hide the other provider.

The adapter uses the same plugin classes and config directory as the legacy storage API.
It never calls `set_config`, `apply_config`, or `run_command`. Its enablement reader merges
stored overrides with built-in defaults in memory and does not create, normalize, or
rewrite `plugins.json`.

## Compatibility Boundary

`/api/capabilities/storage.pooling`, `/api/capabilities/storage.protection`, and
`/api/extensions` now expose the first-party storage providers through the shared
registry. Existing `/api/storage/plugins/*` routes remain unchanged for tailored setup,
preview, apply, recovery, logs, and streamed commands.

Pools and Protection still retain their frontend compatibility adapter for partial
rollback and mixed-version recovery. Registry status is primary; legacy detail data only
fills missing domain details. This fallback can be retired after the final route and
canary gates.

Capability status remains on-demand. CP-017 adds no polling, scheduler, background
command, database, or privileged helper call.

## Existing-Instance Deployment

No manual migration is required:

- Existing `plugins.json`, `mergerfs.json`, `snapraid.json`, SnapRAID state, schedules,
  logs, and generated system files remain unchanged.
- Provider IDs, plugin API routes, config schemas, and command parameters remain stable.
- Updating does not enable or disable a provider, save or apply configuration, mount or
  unmount a pool, or run a SnapRAID operation.
- MergerFS and SnapRAID do not need to be reinstalled or reconfigured.
- No frontend source changed; the existing committed `static/v2` bundle remains fresh,
  so the target Pi does not need npm.

Use the normal LimeOS updater and restart. On Holly, compare the Pools and Protection
summaries with the legacy Plugins details, then confirm `/api/extensions` lists both
built-in providers with the expected enabled and configured lifecycle state.

## Verification

- Full non-E2E suite: 1,684 passed, 1 skipped
- Adapter, registry, and capability API suite: 74 passed
- Storage plugin, plugin manager, MergerFS, SnapRAID, and manifest contracts: 103 passed
- Pools and Protection Playwright regression: 25 passed across desktop, tablet, and
  phone profiles where parameterized
- Ruff lint, manifest validation, Python compilation, bundle freshness, and
  `git diff --check`: passed

CP-020 owns the full cross-domain release gate. CP-021 records the target-Pi canary and
rollback evidence.
