# Capability Providers and Storage Surfaces

Date: 2026-07-16
Status: Sprint 4 active; CP-013 complete, CP-014 next
Tracking prefix: `CP`

## Goal

Give Disks, Pools, Protection, Extensions, and Integrations clear ownership while
retaining the current plugin system as the implementation foundation.

Users should operate storage through domain pages. Administrators should manage
installed provider packages under Settings. Provider authors should be able to add
capabilities, setup fields, status, and actions without shipping arbitrary frontend
code.

## Product Model

| Concept | Meaning | Primary surface |
| --- | --- | --- |
| App | A containerized workload deployed by LimeOS | App Catalog, Containers, Stacks |
| Extension | An installed package that adds LimeOS capabilities | Settings > Advanced > Extensions |
| Provider | An implementation of one or more capabilities | The owning capability page |
| Capability | A user-facing function such as pooling or protection | Pools, Protection, Integrations |
| Integration | A configured connection to an external system | Integrations |

Examples:

| Provider | Capability | User surface |
| --- | --- | --- |
| MergerFS | `storage.pooling` | Pools |
| SnapRAID | `storage.protection` | Protection |
| Mattermost | `integration.chat` | Integrations |
| Claude Code | `agent.provider` | AI Agents within Integrations |

An extension package may provide an integration, but users configure the connection
through Integrations. Extensions manages code installation, compatibility, enablement,
updates, diagnostics, and removal.

## Product Decisions

1. Move the user-facing Plugins surface to Settings > Advanced and rename it
   Extensions.
2. Keep `plugin` names in backend code and persisted configuration until a separate
   compatibility migration is justified.
3. Keep Pools and Protection visible in primary navigation so users can discover the
   capabilities before installing a provider.
4. Show operational cards only for enabled providers.
5. When no provider is enabled, show a focused explanation and an administrator-only
   `Add provider` action.
6. Separate pooling from protection. SnapRAID is a protection provider, not a pool.
7. Use one capability-provider contract across storage and integrations while keeping
   their user-facing workflows separate.
8. Render third-party provider pages from schemas and bounded action descriptors.
9. Permit tailored first-party renderers for workflows that cannot be expressed clearly
   with the generic renderer.
10. Do not load arbitrary JavaScript, React components, HTML, or remote assets from
    extensions in the first release.
11. Restrict extension installation, removal, update, and enablement to administrators.
12. Allow authorized non-admin users to view status and run only actions permitted by
    the capability's policy.

## Navigation and Routes

Primary navigation:

```text
Home
Containers
Stacks
App Catalog
Disks
Pools
Protection
Mounts
Shares
Integrations
System Health
Network
Settings
```

Settings contains:

```text
General
Updates
Backup and Restore
Advanced
  Extensions
  Extension diagnostics
```

Route contract:

| Route | Purpose |
| --- | --- |
| `/disks` | Physical devices, partitions, health, capacity, mounts |
| `/pools` | Enabled `storage.pooling` providers and configured pools |
| `/protection` | Enabled `storage.protection` providers and protection jobs |
| `/settings/extensions` | Installed extension packages and provider enablement |
| `/settings/extensions/:id` | Extension compatibility, diagnostics, and administration |
| `/pools/:providerId` | Provider setup or administration within the Pools domain |
| `/protection/:providerId` | Provider setup or administration within Protection |
| `/plugins` | Compatibility redirect to `/settings/extensions` |

Existing API routes and stored plugin identifiers remain valid during the migration.

## Provider Contract

The existing plugin registry grows an additive provider manifest. The final field names
are fixed by `CP-001`, but the contract must cover:

```yaml
id: mergerfs
name: MergerFS
version: "2"
compatibility:
  limeos_min: "1.0"
capabilities:
  - id: storage.pooling
    surface: pools
    renderer: mergerfs
    setup_schema: mergerfs-pool-v1
    status_schema: pool-status-v1
    actions:
      - mount
      - unmount
      - balance
permissions:
  view: storage.read
  configure: extensions.admin
```

The manifest is declarative and non-secret. Runtime credentials and configuration stay
in the existing protected runtime paths.

Each capability exposes bounded contracts for:

- Summary state and health
- Setup and configuration schema
- Validation errors tied to fields
- Metrics and recent activity
- Available actions, parameters, and danger level
- Progress events and final result
- Required role or permission
- Diagnostics and recovery information

The LimeOS frontend owns navigation, layout, forms, confirmations, focus management,
progress consoles, error states, and audit links.

## Renderer Strategy

### Generic Renderer

The default renderer supports:

- Text, number, select, checkbox, path, and secret-reference fields
- Required fields, ranges, choices, and field-level validation
- Read-only status metrics and health badges
- Bounded commands with parameter schemas
- Confirmation for destructive operations
- Setup, save, apply, disable, and repair states

### Tailored Renderers

First-party renderers may be registered by capability and renderer ID. Initial tailored
surfaces are:

- MergerFS branch selection, ordering, policy, minimum free space, preview, and mount
- SnapRAID data/parity assignment, schedule, sync, scrub, status, and recovery
- Mattermost installation, alert policy, silences, channels, and delivery tests
- AI Agent provider authentication, permissions, usage, and audit

A missing tailored renderer falls back to the generic renderer when the manifest uses
supported schemas. Unsupported schema versions fail closed with a compatibility message.

## Page Designs

### Disks

Disks owns physical storage only:

- Header summary: device count, healthy/warning/failing counts, mounted capacity, and
  unallocated or unmounted count
- Device cards: model, bus, health, temperature when available, size, mounted usage,
  and compact actions
- Partition rows: filesystem, mount point, size, usage, mount state, and overflow actions
- Suggested mounts as an action band rather than a dominant page section
- SMART details and self-tests in a focused device view
- Clear distinction between free filesystem capacity and unused/unpartitioned space

Disks links to a pool or protection provider when a device is assigned. It does not
configure pooling or parity itself.

### Pools

Pools consumes `storage.pooling` providers:

- Header summary: pools, mounted state, aggregate capacity, free space, and warnings
- One card per configured pool, rendered by its provider
- Provider identity shown as secondary metadata, not as the primary object
- Pool details: branches, mount point, policy, capacity, health, and recent action
- Compact operational actions; configuration and destructive actions live in More
- Empty state with available pooling providers and an administrator-only setup action
- Enabled but unconfigured providers appear as setup rows, not healthy pools

### Protection

Protection consumes `storage.protection` providers:

- Protected and unprotected disk counts
- Last successful sync/check and next scheduled run
- Required action, degraded, or error state at the top
- Provider-specific cards for parity, replication, snapshots, or backup protection
- SnapRAID card tailored to data/parity assignments, sync requirement, scrub age,
  schedule, and recovery information
- Empty state with available protection providers

### Extensions

Extensions is an administrator surface under Settings > Advanced:

- Dense installed-extension list grouped by capability
- Name, version, source, compatibility, enabled providers, health, and update state
- Install and remove actions with explicit trust and permission information
- Direct links to the capability pages where setup and normal operation occur
- Diagnostics for manifest errors, unsupported schemas, failed services, and logs
- `Other capabilities` group for extensions without a dedicated LimeOS domain page

Extensions does not duplicate provider setup forms already owned by Pools, Protection,
or Integrations.

## Access and Security

| Operation | Administrator | Authorized user |
| --- | --- | --- |
| View extension and capability status | Yes | Yes |
| Install, update, remove extension | Yes | No |
| Enable or disable provider | Yes | No |
| Change provider configuration | Yes | No by default |
| Run read-only status or diagnostic action | Yes | Policy-controlled |
| Run mutating capability action | Yes, with confirmation | Denied by default |

All mutating requests retain authentication, CSRF validation, fixed parameter schemas,
server-side authorization, progress bounds, redaction, and audit records. A manifest
cannot grant permissions or add arbitrary helper commands.

## Delivery Strategy

The migration remains additive until the final navigation sprint:

1. Add capability contracts behind the current Plugins and Pools pages.
2. Adapt current MergerFS and SnapRAID plugins without changing stored configuration.
3. Add new domain pages and routes while the legacy routes remain available.
4. Move extension administration into Settings.
5. Redirect `/plugins` only after capability pages pass target-Pi verification.

Each sprint ends with a deployable commit range and Holly canary evidence. No sprint may
require a database reset, plugin reinstall, or recreation of existing MergerFS or
SnapRAID configuration.

## Sprint Plan

### Sprint 0: Contracts and Baseline

Goal: fix terminology, compatibility, and test fixtures before changing behaviour.

| ID | Work package | Depends on | Status | Deliverable |
| --- | --- | --- | --- | --- |
| CP-000 | Baseline and product contract | Current pages | Complete | [`Docs/LIMEOS_CAPABILITY_PROVIDERS_CP000_BASELINE.md`](../../Docs/LIMEOS_CAPABILITY_PROVIDERS_CP000_BASELINE.md) |
| CP-001 | Capability manifest contract | CP-000 | Complete | [`Docs/LIMEOS_CAPABILITY_PROVIDERS_CP001_CONTRACT.md`](../../Docs/LIMEOS_CAPABILITY_PROVIDERS_CP001_CONTRACT.md) and versioned schemas under `config/schemas/` |
| CP-002 | Provider fixtures and contract tests | CP-001 | Complete | Executable Draft 7 and semantic contract tests with provider, setup, status, action, invalid, and incompatible fixtures under `tests/fixtures/capability_providers/` |

Exit gate:

- Contracts cover storage and integration providers without coupling their user surfaces.
- Existing provider configuration round-trips unchanged.
- Unsupported manifests and renderer versions fail closed.

### Sprint 1: Provider Registry Foundation

Goal: expose capabilities without replacing current pages.

| ID | Work package | Depends on | Status | Deliverable |
| --- | --- | --- | --- | --- |
| CP-003 | Capability registry service | CP-001 | Complete | Framework-neutral `capability_registry_service.py` with offline contract validation, isolated discovery, compatibility, lifecycle normalization, redaction, and capability health aggregation |
| CP-004 | Capability API | CP-003 | Complete | [`Docs/LIMEOS_CAPABILITY_PROVIDERS_CP004_API.md`](../../Docs/LIMEOS_CAPABILITY_PROVIDERS_CP004_API.md): authenticated list/detail APIs with stable failures and lifecycle transport secured by the CP-006 `extensions.admin` policy |
| CP-005 | Generic renderer foundation | CP-001, CP-002 | Complete | [`Docs/LIMEOS_CAPABILITY_PROVIDERS_CP005_RENDERER.md`](../../Docs/LIMEOS_CAPABILITY_PROVIDERS_CP005_RENDERER.md): typed schema forms, field errors, bounded status rendering, declared action confirmation, and monotonic progress handling |
| CP-006 | Security and audit boundary | CP-003, CP-004 | Complete | [`Docs/LIMEOS_CAPABILITY_PROVIDERS_CP006_SECURITY.md`](../../Docs/LIMEOS_CAPABILITY_PROVIDERS_CP006_SECURITY.md): fixed roles and permissions, authenticated read checks, admin lifecycle policy, CSRF coverage, request allowlists, recursive redaction, and value-free audit events |

Exit gate:

- Current Plugins and Pools behaviour remains unchanged.
- Registry failure does not prevent Disks or existing integrations from loading.
- Arbitrary frontend code and helper commands are rejected.

### Sprint 2: Extensions Administration

Goal: move package management out of the normal storage workflow.

| ID | Work package | Depends on | Status | Deliverable |
| --- | --- | --- | --- | --- |
| CP-007 | Extensions list and details | CP-004 | Complete | [`Docs/LIMEOS_CAPABILITY_PROVIDERS_CP007_EXTENSIONS.md`](../../Docs/LIMEOS_CAPABILITY_PROVIDERS_CP007_EXTENSIONS.md): Settings > Advanced list, compatibility, diagnostics, source, version, and capability links |
| CP-008 | Extension lifecycle controls | CP-004, CP-006 | Complete | [`Docs/LIMEOS_CAPABILITY_PROVIDERS_CP008_LIFECYCLE.md`](../../Docs/LIMEOS_CAPABILITY_PROVIDERS_CP008_LIFECYCLE.md): admin install, enable, disable, update, remove, repair, and confirmation flows |
| CP-009 | Navigation and route compatibility | CP-007 | Complete | [`Docs/LIMEOS_CAPABILITY_PROVIDERS_CP009_ROUTES.md`](../../Docs/LIMEOS_CAPABILITY_PROVIDERS_CP009_ROUTES.md): shared Advanced navigation, stable extension deep links, canonical paths, and guarded `/plugins` redirect preparation |

Exit gate:

- Non-admin users cannot mutate extension state through UI or API.
- Existing extensions can be inspected without opening raw JSON.
- Capability links lead to an owning page or a clear not-yet-available state.

### Sprint 3: Disks Operational Page

Goal: make physical storage health and allocation glanceable.

| ID | Work package | Depends on | Status | Deliverable |
| --- | --- | --- | --- | --- |
| CP-010 | Disk summary contract | CP-000 | Complete | [`Docs/LIMEOS_CAPABILITY_PROVIDERS_CP010_DISK_SUMMARY.md`](../../Docs/LIMEOS_CAPABILITY_PROVIDERS_CP010_DISK_SUMMARY.md): bounded health, capacity, allocation, provider-assignment, and partial-failure contract |
| CP-011 | Disk card and partition redesign | CP-010 | Complete | [`Docs/LIMEOS_CAPABILITY_PROVIDERS_CP011_DISK_CARDS.md`](../../Docs/LIMEOS_CAPABILITY_PROVIDERS_CP011_DISK_CARDS.md): fleet summary, compact device and partition usage, provider links, and overflow actions |
| CP-012 | Disk workflow hardening | CP-011 | Complete | [`Docs/LIMEOS_CAPABILITY_PROVIDERS_CP012_DISK_WORKFLOWS.md`](../../Docs/LIMEOS_CAPABILITY_PROVIDERS_CP012_DISK_WORKFLOWS.md): compact mount actions, confirmation safety, SMART recovery, stale-refresh handling, and responsive failure coverage |

Exit gate:

- A user can identify failing, full, unmounted, and provider-assigned disks at a glance.
- No new continuous polling or privileged helper calls are introduced.
- Existing mount, unmount, and SMART workflows remain compatible.

### Sprint 4: Pools and Protection Domains

Goal: operate enabled capabilities through provider-driven pages.

| ID | Work package | Depends on | Status | Deliverable |
| --- | --- | --- | --- | --- |
| CP-013 | Pools capability page | CP-003..CP-006 | Complete | [`Docs/LIMEOS_CAPABILITY_PROVIDERS_CP013_POOLS.md`](../../Docs/LIMEOS_CAPABILITY_PROVIDERS_CP013_POOLS.md): summary, empty/setup states, generic provider rendering, compatibility data, and pool routes |
| CP-014 | MergerFS tailored renderer | CP-013 | Planned | Branch editor, policy, preview, apply, mount, unmount, balance, and diagnostics |
| CP-015 | Protection capability page | CP-003..CP-006 | Planned | Summary, empty/setup states, generic protection rendering, and protection routes |
| CP-016 | SnapRAID tailored renderer | CP-015 | Planned | Assignment, schedule, sync, scrub, status, recovery, and diagnostics |
| CP-017 | Provider migration adapters | CP-014, CP-016 | Planned | Existing plugin/config/status payloads mapped to capability contracts without reinstall |

Exit gate:

- Pools shows only enabled pooling providers and configured pools.
- Protection shows only enabled protection providers and configured protection sets.
- Empty pages remain discoverable and let administrators add a provider.
- Existing MergerFS and SnapRAID installations operate without configuration changes.

### Sprint 5: Integration Alignment and Rollout

Goal: prove the shared framework without merging the user-facing domains.

| ID | Work package | Depends on | Status | Deliverable |
| --- | --- | --- | --- | --- |
| CP-018 | Integration provider adapter | CP-003..CP-006 | Planned | Mattermost or AI provider represented in the capability registry with unchanged setup UX |
| CP-019 | Final navigation migration | CP-007, CP-013, CP-015 | Planned | Plugins removed from primary nav, Extensions enabled under Advanced, redirects activated |
| CP-020 | Cross-domain hardening | CP-010..CP-019 | Planned | Accessibility, responsive, recovery, compatibility, security, and bundle tests |
| CP-021 | Holly canary and release signoff | CP-020 | Planned | Upgrade, operation, rollback, and evidence checklist on `holly@192.168.0.45` |

Exit gate:

- Integration setup and operation remain independent from extension administration.
- All old deep links redirect to a valid owning page.
- Holly completes the canary checklist without reinstalling providers or losing config.

## Parallel Work

After `CP-001` fixes the contracts, these streams can proceed in parallel:

- **Platform:** CP-003, CP-004, and CP-006
- **Generic frontend:** CP-005, then CP-007
- **Disk UX:** CP-010 through CP-012
- **Pooling:** CP-013 and CP-014 using contract fixtures
- **Protection:** CP-015 and CP-016 using contract fixtures
- **Verification:** prepare CP-020 fixtures and security cases from Sprint 1 onward

CP-017 integrates the first-party provider streams. CP-019 changes navigation only after
the new domain routes are complete.

## Test Strategy

Backend tests cover:

- Manifest parsing, schema versions, compatibility, and duplicate capabilities
- Provider discovery, enablement, partial failure, and health precedence
- Role enforcement, CSRF, fixed action parameters, redaction, and audit
- Migration adapters for current MergerFS and SnapRAID configuration
- Generic setup validation and progress-event bounds

Frontend and Playwright tests cover:

- Administrator and non-admin states
- No-provider, disabled, unconfigured, healthy, warning, error, and incompatible states
- Provider setup, configuration, diagnostics, actions, and recovery
- Stable routes, redirects, focus restoration, keyboard operation, and confirmations
- Desktop, tablet, and phone layouts without horizontal overflow
- Existing Disks, MergerFS, SnapRAID, Mattermost, and AI Agent workflows

The production bundle remains committed. Provider installation must not require npm or a
frontend build on the target Pi.

## Deployment Checklist

Every sprint deployment records:

```text
Sprint:
Commit range:
Deployed revision:
Schema/manifest version:
Target host:
Preflight result:
Automated test result:
Manual workflow result:
Rollback result:
Known issues:
Signoff:
```

Holly preflight:

1. Record the current revision and working-tree state without deleting runtime files.
2. Export extension configuration and record enabled providers.
3. Record MergerFS pools, SnapRAID assignments, schedules, mounts, and current health.
4. Confirm dashboard, helper, alert, agent, and provider services are healthy.
5. Confirm the committed frontend bundle exists before update.

Canary verification:

1. Update through the normal LimeOS update flow.
2. Confirm the deployed revision and production bundle.
3. Hard reload the browser after the service restart.
4. Verify Disks inventory, usage, SMART, mount, and unmount confirmation.
5. Verify MergerFS configuration, mount state, capacity, and a read-only status action.
6. Verify SnapRAID configuration, schedule, status, and a non-destructive check.
7. Verify Extensions role restrictions and diagnostics.
8. Verify Mattermost alerts and AI Agent responses remain operational.
9. Run the full automated suite and retain browser evidence at desktop and phone widths.

Rollback:

1. Prefer reverting the sprint commits and redeploying the previous committed bundle.
2. Keep manifest and API changes backward-compatible for at least one release boundary.
3. Do not delete provider configuration during rollback.
4. Restore configuration only from the recorded preflight export when a migration changed
   persisted data.
5. Re-run the same canary checks against the previous revision.

## Release Acceptance

1. A user can explain Apps, Extensions, Providers, Capabilities, and Integrations from
   their labels and page placement.
2. Plugins no longer appear as a normal storage workflow in primary navigation.
3. Administrators manage extension packages under Settings > Advanced.
4. Pools and Protection remain discoverable before a provider is enabled.
5. Only enabled providers produce operational cards.
6. Generic third-party providers can render setup, status, and bounded actions without
   frontend code.
7. MergerFS and SnapRAID retain tailored workflows and existing configuration.
8. Extension manifests cannot grant permissions, inject frontend code, or add arbitrary
   privileged commands.
9. Disks clearly distinguishes physical health, filesystem usage, mount state, and
   provider assignment.
10. Existing Mattermost, alerting, AI Agent, mount, share, and update workflows pass
    regression tests.
11. Target-Pi updates use the committed bundle and require no npm installation.
12. A tested rollback returns Holly to the previous release without losing provider
    configuration.

## Deferred Work

- Arbitrary provider-supplied frontend bundles or remote UI assets
- A third-party JavaScript component SDK
- Automatic installation based only on opening an empty capability page
- A public extension marketplace or trust-signing service
- Multiple simultaneous providers for one exclusive capability without conflict rules
- General non-storage capability pages without a product owner
- Renaming backend plugin modules, APIs, and persisted paths
- Non-admin mutation of provider configuration
