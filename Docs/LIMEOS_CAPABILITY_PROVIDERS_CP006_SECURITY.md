# LimeOS Capability Providers CP-006 Security Boundary

Date: 2026-07-17

Status: Implemented

Scope: CP-006 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

## Server-Owned Roles

Capability permissions are assigned by LimeOS. Provider manifests may request a known
permission for a declared operation, but cannot create permissions, assign roles, or
grant access to a user.

| Role | Permissions |
| --- | --- |
| `admin` | `capability.view`, `capability.configure`, `capability.diagnose`, `capability.operate`, `extensions.admin` |
| `operator` | `capability.view`, `capability.diagnose` |
| `viewer` | `capability.view` |

For an existing installation without an explicit role configuration, the first
configured LimeOS user is assigned `admin`; additional configured users are assigned
`viewer`. This preserves single-user administration while denying mutation to users
added later.

Multi-user installations can set a complete role map with:

```text
PIHEALTH_USER_ROLES=alice:admin,bob:operator,carol:viewer
```

Every configured login user must appear exactly once. Unknown users, unknown roles,
duplicates, and incomplete maps stop application startup. Unknown or removed session
users receive no capability permissions. Login and authentication-check responses now
include the effective `role` and sorted `permissions` for later UI policy checks.

## API Enforcement

All capability and extension reads require `capability.view`. Extension install,
enable, disable, update, repair, and remove operations require `extensions.admin`.
Authorization is checked on the server for every request; frontend visibility is not a
security control.

The global authenticated mutation boundary continues to require the session CSRF token
in `X-CSRF-Token` before a lifecycle handler can authorize or dispatch an operation.

Lifecycle requests use fixed schemas:

- Install accepts only `type`, `source`, `id`, `entry`, and `class_name`.
- `type` is currently `github` or `pip`; `type` and `source` are required.
- Provider IDs, Python entry paths, and class names use bounded server patterns.
- Enable, disable, update, and repair accept an empty JSON object.
- Remove accepts no request body.
- Unknown fields and malformed values return `invalid_lifecycle_parameters` without
  echoing field values.

CP-008 provides the compatibility lifecycle service and administrator confirmation UI.
An explicitly missing lifecycle dependency still fails closed with
`extension_lifecycle_unavailable`.

## Redaction and Audit

Registry status and lifecycle service results use the same recursive redaction policy.
Sensitive keys, credentials in URLs, authorization values, Mattermost hook URLs, and
secret-looking text are replaced before serialization. Unexpected exceptions remain
private and map to stable public errors.

Each lifecycle attempt records one bounded audit event with these fields:

- Domain and event name
- Authenticated actor
- Required permission
- Fixed lifecycle action
- Validated provider ID when applicable
- Authorization decision
- Outcome and stable result code

Request fields, request values, provider output, exception text, and credentials are
never written to the lifecycle audit event. Audit writer failure cannot expose secrets
or bypass the authorization decision.

## Manifest Boundary

The CP-001 schemas remain the only accepted manifest vocabulary. CP-003 validates
manifests locally with `additionalProperties: false`, fixed permission constants,
server-owned capability surfaces, and tailored-renderer allowlists. CP-006 role mapping
does not consume role or grant data from provider payloads.

## Verification

- CP-006 focused backend suite: 170 passed, 1 skipped
- Full non-browser suite: 1,646 passed, 1 skipped
- Browser parity suite: 123 passed
- Ruff lint and `git diff --check`: passed

No legacy storage, Pools, or Integrations route changed in this slice. No frontend
source or production bundle changed.
