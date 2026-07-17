# LimeOS Capability Providers CP-000 Baseline and Product Contract

Date: 2026-07-17

Status: Accepted for CP-001 contract design

Scope: CP-000 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

Repository baseline: `05e05d3`

## Decision

Proceed with an additive capability-provider contract over the existing storage plugin
system. Keep current plugin identifiers, configuration paths, and APIs compatible while
new domain pages take ownership of normal operations.

The user-facing product model is fixed as follows:

| Concept | Meaning | Owning surface |
| --- | --- | --- |
| App | A containerized workload deployed by LimeOS | App Catalog, Containers, Stacks |
| Extension | An installed package that adds LimeOS capabilities | Settings > Advanced > Extensions |
| Provider | An implementation of one or more capabilities | The page that owns the capability |
| Capability | A user-facing function such as pooling or protection | Pools, Protection, Integrations |
| Integration | A configured connection to an external system | Integrations |

`Plugin` remains an internal compatibility term. It is not the long-term label for an
ordinary storage workflow.

## Current-State Inventory

### Routes and Page Ownership

The React application currently defines these relevant routes in
`frontend/src/app/routes.tsx`:

| Current route | Current owner | Baseline behaviour |
| --- | --- | --- |
| `/disks` | `DisksPage` | Physical inventory, SMART, suggested mounts, mount/unmount, and filesystem usage |
| `/plugins` | `StoragePage` | All enabled and disabled storage plugins |
| `/pools` | `StoragePage` | Plugins whose registry metadata has `kind: pool` |
| `/mounts` | Mounts page | Mounted filesystem operations |
| `/shares` | Shares page | Network share operations |
| `/integrations` | `IntegrationsPage` | Bespoke Mattermost, Stack Notifications, and AI Agent workflows |
| `/settings` | Settings page | General system settings; no Extensions section yet |

The deployed browser prefix is `/v2`, while the React route contract remains relative.
For example, the browser URL `/v2/pools` maps to the React route `/pools`.

`frontend/src/pages/storage-page.tsx` currently selects plugin or pool behaviour from
the pathname. It uses provider-specific components for MergerFS and SnapRAID and a
generic plugin card for other providers. This is useful implementation material, but it
also causes package administration, provider setup, and domain operation to share one
page.

Existing tailored storage UI includes:

- MergerFS branch selection and configuration
- SnapRAID disk assignment and scheduling
- Bounded command execution and progress display
- Status, recovery information, and latest logs
- Guided configuration with an advanced JSON fallback

### Runtime Plugin Model

The existing runtime is an in-process Python plugin system:

| Component | Current responsibility |
| --- | --- |
| `storage_plugins/base.py` | Abstract storage configuration, validation, status, recovery, and command contract |
| `storage_plugins/remote_base.py` | Separate abstraction for remote mount providers |
| `storage_plugins/registry.py` | In-process registry of enabled plugin instances and their status metadata |
| `plugin_manager.py` | Installed/enabled state, source metadata, GitHub installation, and dynamic module loading |
| `storage_plugins/__init__.py` | Authenticated `/api/storage/plugins` transport and lifecycle endpoints |
| `storage_read_service.py` | Framework-neutral list, detail, status, recovery, and log reads |
| `pihealth_helper.py` | Root-owned, typed helper operations for supported install/remove workflows |

`StoragePlugin.KIND` is currently a UI hint rather than a capability contract. A value
of `pool` causes pool-aware cards and editors to be shown. This groups MergerFS pooling
and SnapRAID protection together even though they solve different problems.

Built-in providers currently include:

| Provider | Current category/kind | Future capability |
| --- | --- | --- |
| MergerFS | Storage / pool | `storage.pooling` |
| SnapRAID | Storage / pool | `storage.protection` |
| SSHFS | Mount | Remote mount capability |
| Rclone | Mount | Remote mount capability |
| Samba | Share | Network share capability |

The registry currently instantiates enabled plugins only. Installed but disabled
extensions remain visible through `PluginManager`, but cannot expose live provider
status through the runtime registry.

### Current Extension Manifest

Third-party GitHub extensions use `pihealth_plugin.json`. The current loader recognises
basic package and entry-point fields such as:

- `id`
- `name`
- `entry`
- `class`
- `category`
- `description`
- `version`

The manifest does not currently declare a manifest version, LimeOS compatibility,
capabilities, permissions, setup schema version, status schema version, renderer, or
bounded action policy.

GitHub extensions are cloned locally and their Python entry point is loaded into the
main LimeOS process. This is a trusted-code model. It is not a sandbox or a signature
boundary. The privileged helper rejects pip installation because that could execute
arbitrary setup code as root.

### Integrations

Mattermost, Stack Notifications, and AI Agents are independent application services
with bespoke APIs and frontend cards. They do not use the storage plugin registry.

The shared capability framework will therefore be introduced through adapters. CP-018
must prove that an integration can advertise capability and health metadata without
replacing or degrading its purpose-built setup workflow.

### Authentication and Authorization

The current application has authenticated and unauthenticated states only:

- User records contain a username and password hash, not a role.
- `login_required` verifies the session but does not distinguish administrators.
- Authenticated state-changing requests are protected by global CSRF validation.
- Storage plugin lifecycle endpoints are authenticated, but are not admin-authorized.
- The frontend displays `admin` as presentation text; it is not evidence of a role.

The accepted product rule that only administrators can install, remove, update, enable,
or disable extensions cannot be enforced by the current identity model. CP-006 must add
a server-side authorization contract before CP-008 exposes the new lifecycle controls.
Frontend visibility alone is not authorization.

## Accepted Route Map

The target route ownership is:

| React route | Browser route | Owner |
| --- | --- | --- |
| `/disks` | `/v2/disks` | Physical device health, partitions, capacity, and mounts |
| `/pools` | `/v2/pools` | Enabled `storage.pooling` providers and configured pools |
| `/pools/:providerId` | `/v2/pools/:providerId` | Provider setup or administration within Pools |
| `/protection` | `/v2/protection` | Enabled `storage.protection` providers and protection sets |
| `/protection/:providerId` | `/v2/protection/:providerId` | Provider setup or administration within Protection |
| `/integrations` | `/v2/integrations` | External connections and their operational policy |
| `/settings/extensions` | `/v2/settings/extensions` | Extension package administration |
| `/settings/extensions/:id` | `/v2/settings/extensions/:id` | Compatibility, diagnostics, source, and lifecycle |
| `/plugins` | `/v2/plugins` | Compatibility redirect to Settings > Advanced > Extensions |

Pools and Protection remain visible even when no provider is enabled. Their empty state
explains the capability and offers an `Add provider` action to an administrator.
Operational cards are produced only by enabled providers.

## Ownership Boundaries

### Disks

Disks owns physical devices, partitions, SMART health, temperature, filesystem usage,
mount state, and links to assigned providers. It does not configure pools or parity.

### Pools

Pools owns configured pool objects and enabled `storage.pooling` providers. MergerFS is
the first tailored pooling provider.

### Protection

Protection owns parity, replication, snapshot, and backup protection status. SnapRAID
is the first tailored protection provider and must no longer appear as a pool.

### Extensions

Extensions owns package source, version, compatibility, installation, update,
enablement, diagnostics, and removal. It links to the capability page for setup and
normal operation rather than duplicating those workflows.

### Integrations

Integrations owns external service configuration, authentication, delivery policy,
silences, usage, and tests. An integration may be supplied by an extension, but users
still configure the connection through Integrations.

## Migration Constraints

The following constraints are release requirements:

1. Keep existing plugin IDs, installed-extension records, and configuration paths.
2. Keep `/api/storage/plugins` compatible while additive capability APIs are introduced.
3. Do not require MergerFS or SnapRAID reinstallation or configuration recreation.
4. Keep `/plugins` usable until Extensions and both storage domain pages are ready, then
   redirect it to `/settings/extensions`.
5. Separate installed, enabled, configured, compatible, and healthy states in the new
   contract. Do not infer one state from another.
6. Preserve provider discovery when a provider is installed but disabled. Runtime
   health may be unavailable, but package and capability metadata must remain visible.
7. Do not allow a manifest to grant permissions or introduce arbitrary privileged
   helper commands.
8. Do not load provider-supplied JavaScript, React, HTML, or remote assets.
9. Keep all action parameters bounded by server-owned schemas and permission policy.
10. Fail closed when a manifest, schema, renderer, or API contract version is unsupported.
11. Isolate a broken provider so Disks, Extensions, and unrelated integrations still load.
12. Retain CSRF checks, redaction, progress limits, confirmations, and audit evidence for
    mutations.
13. Keep the production frontend bundle committed. A target Pi must not need Node or npm.
14. Introduce no continuous polling or privileged helper overhead as part of discovery.
15. Keep contract and API changes backward-compatible for at least one release boundary.

## Contract Gaps for CP-001

CP-001 must define a versioned, declarative manifest covering:

| Area | Required decision |
| --- | --- |
| Identity | Stable package ID, provider ID, display name, and version |
| Compatibility | Manifest version and supported LimeOS/API/schema ranges |
| Capabilities | One or more capability IDs with explicit ownership and exclusivity rules |
| Presentation | Surface, renderer ID, generic fallback, and unsupported-renderer behaviour |
| Setup | Versioned field schema, secret references, defaults, and validation errors |
| Status | Versioned health, summary metrics, recent activity, and partial failure |
| Actions | Stable action IDs, parameter schemas, danger level, progress, timeout, and result |
| Permissions | Server-owned view, configure, lifecycle, diagnostic, and mutation policies |
| Lifecycle | Installed, enabled, configured, compatible, available, and healthy states |
| Diagnostics | Stable error codes, recovery hints, log references, and redaction rules |

CP-001 must also decide how current Python attributes and schemas adapt to this manifest
without forcing every built-in provider to be rewritten at once.

The manifest can request a known permission but cannot define or grant one. CP-006 owns
the role model, enforcement, and audit boundary. CP-004 lifecycle endpoints must not be
considered complete until that enforcement exists.

## Security Position

The first capability-provider release accepts the current trusted Python extension
model but does not expand its trust surface. Installation must disclose that an
extension runs in the LimeOS application process.

The release does not claim sandboxing, code signing, marketplace trust, or safe
execution of arbitrary third-party code. Those claims require separate architecture and
threat-model work.

## CP-000 Acceptance Evidence

- Current routes and page ownership are recorded.
- Current plugin registry, manager, helper, API, and integration boundaries are recorded.
- Apps, Extensions, Providers, Capabilities, and Integrations have accepted meanings.
- Pools and Protection are separate domains.
- SnapRAID is classified as protection; MergerFS is classified as pooling.
- Target routes and compatibility redirects are fixed.
- Persistence, API, target-Pi, security, and rollback constraints are explicit.
- The missing administrator role is recorded as a delivery dependency, not assumed.
- CP-001 has a bounded list of contract decisions.

## Non-Goals

CP-000 does not change runtime behaviour, routes, APIs, persisted configuration,
navigation, authorization, or the production bundle. It does not approve arbitrary
provider frontend code or privileged commands.

## Handoff

CP-001 can now define the manifest and schemas against this baseline. CP-002 must then
freeze fixtures for MergerFS, SnapRAID, generic pooling, generic protection, invalid,
incompatible, disabled, and partially failing providers before registry implementation
begins.
