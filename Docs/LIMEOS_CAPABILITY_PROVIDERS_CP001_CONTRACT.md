# LimeOS Capability Providers CP-001 Contract

Date: 2026-07-17

Status: Accepted for CP-002 fixtures and contract tests

Scope: CP-001 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

Baseline: `5e61b64`

## Decision

Capability providers use versioned, declarative contracts. The first contract version
is `1` and uses JSON Schema Draft 7 to match existing LimeOS schemas.

The contract consists of:

| Contract | Schema |
| --- | --- |
| Provider manifest | `config/schemas/capability-provider-manifest.schema.json` |
| Permission request | `config/schemas/capability-provider-permissions.schema.json` |
| Renderer request | `config/schemas/capability-provider-renderer.schema.json` |
| Generic setup | `config/schemas/capability-provider-setup.schema.json` |
| Runtime status | `config/schemas/capability-provider-status.schema.json` |
| Actions and events | `config/schemas/capability-provider-actions.schema.json` |

All top-level objects reject unknown fields. Unsupported versions fail closed. CP-003
will load and index these contracts; CP-004 will expose them through authenticated APIs.

## Provider Manifest

The v1 manifest identifies the provider, its runtime adapter, compatibility, and one or
more capabilities. A representative MergerFS manifest is:

```json
{
  "manifest_version": "1",
  "id": "mergerfs",
  "name": "MergerFS",
  "description": "Combine filesystem branches into a storage pool.",
  "version": "2.40.2",
  "runtime": {
    "kind": "builtin-python",
    "entry": "storage_plugins/mergerfs_plugin.py",
    "class": "MergerFSPlugin"
  },
  "compatibility": {
    "capability_api": "1"
  },
  "capabilities": [
    {
      "id": "storage.pooling",
      "surface": "pools",
      "renderer": {
        "schema_version": "1",
        "id": "mergerfs",
        "mode": "tailored",
        "fallback": "generic"
      },
      "permissions": {
        "schema_version": "1",
        "view": "capability.view",
        "configure": "capability.configure",
        "lifecycle": "extensions.admin"
      },
      "setup": {
        "contract_version": "1",
        "schema_id": "mergerfs-pool-v1"
      },
      "status": {
        "contract_version": "1",
        "schema_id": "pool-status-v1"
      },
      "actions": [
        {
          "id": "mount",
          "label": "Mount pool",
          "description": "Mount the selected MergerFS pool.",
          "intent": "mutation",
          "permission": "capability.operate",
          "timeout_seconds": 60,
          "parameters": [
            {
              "name": "pool_name",
              "label": "Pool",
              "type": "select",
              "required": true,
              "source": "status.details.pools[].name"
            }
          ],
          "confirmation": {
            "title": "Mount pool?",
            "message": "Mount the selected pool using its saved configuration.",
            "confirm_label": "Mount"
          },
          "result_mode": "stream"
        }
      ]
    }
  ]
}
```

### Runtime Kinds

| Kind | Purpose | Entry point |
| --- | --- | --- |
| `builtin-python` | LimeOS-owned Python provider | Required |
| `github-python` | Installed trusted Python extension | Required |
| `integration-adapter` | Metadata adapter over an existing LimeOS service | Forbidden |

An integration adapter advertises an existing service. It does not dynamically import
an extension module.

### Compatibility

`capability_api` is required and fixed at `1`. Optional `limeos_min` and `limeos_max`
values use three-part semantic versions. The registry, not the manifest, compares the
running LimeOS version and reports `compatible`, `incompatible`, or `unknown`.

The manifest cannot relax version checks. An unknown manifest, capability API, setup,
status, actions, or renderer version is incompatible.

### Semantic Validation

JSON Schema validates shape. The CP-003 loader must also reject:

- Duplicate provider IDs
- Duplicate capability IDs within one provider
- Duplicate action IDs within one capability
- Duplicate setup field or section IDs
- Section references to fields that do not exist
- Minimum values greater than maximum values
- A `limeos_min` version greater than `limeos_max`
- A capability whose surface is not owned by its capability ID
- A tailored renderer not registered for the provider and capability
- An action permission or helper operation not registered by LimeOS policy

The manifest does not decide whether a capability is exclusive. LimeOS owns conflict
policy for each capability ID.

## Permission Contract

The manifest requests fixed permission names:

| Request | Meaning |
| --- | --- |
| `capability.view` | Read capability and extension status |
| `capability.configure` | Change provider configuration |
| `extensions.admin` | Install, update, enable, disable, or remove an extension |
| `capability.diagnose` | Run an approved read-only diagnostic action |
| `capability.operate` | Run an approved capability mutation |

The manifest cannot create permissions, grant them to a user, or change role mappings.
CP-006 owns the server-side role and authorization model. Until CP-006 is complete, new
extension lifecycle APIs cannot claim administrator-only enforcement.

## Renderer Contract

`generic` renderers use LimeOS-owned setup, status, and action components. Tailored
renderers are LimeOS frontend modules registered by renderer ID.

The registry must allowlist a tailored renderer against all three of:

1. Provider ID
2. Capability ID
3. Renderer ID

A third-party manifest cannot select a first-party renderer merely by naming it. When a
tailored renderer is unavailable, `fallback: generic` is allowed only if every referenced
contract version is supported. Otherwise the capability fails closed with an
incompatibility state.

No renderer contract permits extension-supplied JavaScript, React components, HTML,
CSS, or remote assets.

## Setup Contract

The generic setup schema supports bounded, flat fields with optional dotted keys:

- Text
- Integer
- Number
- Boolean
- Select
- Path
- Secret reference

Sections group existing field keys; they do not create nested cards or new data. Complex
collections such as MergerFS branches and SnapRAID drive assignments require a tailored
renderer in v1.

A secret-reference field contains only an identifier for a secret held by a protected
backend store. Its schema cannot contain a default value, placeholder, validation
pattern, secret value, credential path, or environment value.

Setup validation returns field-scoped errors using this envelope:

```json
{
  "schema_version": "1",
  "valid": false,
  "errors": [
    {
      "field": "mount_point",
      "code": "invalid_path",
      "message": "Mount point must be below /mnt."
    }
  ]
}
```

Error codes are stable and non-secret. Messages may add detail but must remain safe for
the authenticated browser and audit record.

## Status Contract

Status separates lifecycle facts from operational health:

```text
installed
enabled
configured
compatibility: compatible | incompatible | unknown
availability: available | unavailable | unknown
health: healthy | warning | error | unknown | disabled | unconfigured |
        incompatible | unavailable
```

The registry applies this precedence before provider health:

1. Not installed: `unavailable`
2. Incompatible: `incompatible`
3. Disabled: `disabled`
4. Runtime unavailable: `unavailable`
5. Not configured: `unconfigured`
6. Provider result: `error`, `warning`, `healthy`, or `unknown`

Providers supply bounded summary items, numeric metrics, issues, and recent activity.
The generic renderer uses those fields only. `details` carries provider-specific data
for a tailored renderer and may not be rendered as raw JSON by default.

A provider status failure does not remove its installed metadata and does not prevent
unrelated capabilities from loading. The registry returns an `unavailable` status with
a stable issue code.

## Action Contract

Every action is declared before it can run. A declaration fixes:

- Stable action ID and label
- Intent: read, diagnostic, mutation, or destructive
- Required server-owned permission
- Timeout from 1 to 3,600 seconds
- Bounded parameters
- Confirmation copy for mutation and destructive actions
- Immediate or streamed result mode

The runtime action catalog repeats the declarations and adds a separate availability
entry for each action. Availability can disable an action with a safe reason without
changing its security classification.

Action parameters support text, integer, number, boolean, select, and path fields.
Select options may be static or sourced from bounded `status.summary` or
`status.details` paths. Action parameters never carry secrets.

An action declaration does not add a Python method, shell command, helper command, or
permission. The provider adapter and server policy must already register the action ID.
Unknown actions and parameters fail before provider execution.

Mutation and destructive actions require server-side authorization and browser
confirmation. Confirmation cannot substitute for authorization. A read action must use
`capability.view`.

Streamed actions emit the `actionEvent` definition from the actions schema. Events have
an operation ID, monotonic sequence, bounded type, and optional progress. API transport
adds ownership, expiry, event-count, output-size, and replay limits.

## Legacy Compatibility

CP-001 does not change the current `pihealth_plugin.json` loader. A file without
`manifest_version` remains a legacy manifest until CP-017.

The migration adapter uses explicit mappings rather than trusting `PLUGIN_KIND`:

| Existing provider | Capability mapping |
| --- | --- |
| MergerFS | `storage.pooling` on Pools |
| SnapRAID | `storage.protection` on Protection |
| SSHFS | Remote mount on Mounts |
| Rclone | Remote mount on Mounts |
| Samba | Network share on Shares |

Existing plugin IDs, configuration files, installed records, API routes, and command
methods remain unchanged. Current command descriptors are adapted into v1 declarations;
their `dangerous` flag cannot be the sole source of read-versus-mutation intent.

## CP-001 Acceptance Evidence

- Every contract has an explicit version and rejects unknown top-level fields.
- The manifest covers storage providers and existing integration adapters.
- Pooling and protection use distinct capability IDs and surfaces.
- Installed, enabled, configured, compatible, available, and healthy remain distinct.
- Permission requests are fixed and cannot grant access.
- Tailored renderers are server-owned and allowlisted.
- Generic setup fields and secret references have bounded behaviour.
- Actions have fixed parameters, permissions, danger intent, confirmation, and timeout.
- Arbitrary frontend code and privileged helper commands remain outside the contract.
- Legacy providers have an additive migration path.

## Handoff

CP-002 must validate the schemas with fixtures for MergerFS, SnapRAID, generic pooling,
generic protection, integration adapters, disabled providers, partial failures, invalid
manifests, and unsupported versions. Tests must cover both structural validation and
the semantic rejection rules listed above.
