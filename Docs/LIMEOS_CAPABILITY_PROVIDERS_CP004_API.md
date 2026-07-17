# LimeOS Capability Providers CP-004 API

Date: 2026-07-17

Status: Implemented

Scope: CP-004 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

## Read API

All read routes require an authenticated LimeOS session and return
`Cache-Control: no-store`.

| Method | Route | Response |
| --- | --- | --- |
| `GET` | `/api/capabilities` | Capability index and registry diagnostics |
| `GET` | `/api/capabilities/:capabilityId` | One capability and relevant diagnostics |
| `GET` | `/api/extensions` | Installed provider extensions and diagnostics |
| `GET` | `/api/extensions/:providerId` | One provider extension and relevant diagnostics |

The transport uses `schema_version: "1"`. Registry discovery and provider status
failures remain successful partial reads with entries in `errors`. A missing, malformed,
or failed registry returns the stable `capability_registry_unavailable` error without
including exception text.

The read API is additive. Existing `/api/storage/plugins`, Pools, and Integrations APIs
remain unchanged.

## Lifecycle API

| Method | Route | Operation |
| --- | --- | --- |
| `POST` | `/api/extensions/install` | Install an extension |
| `POST` | `/api/extensions/:providerId/enable` | Enable a provider |
| `POST` | `/api/extensions/:providerId/disable` | Disable a provider |
| `POST` | `/api/extensions/:providerId/update` | Update an extension |
| `POST` | `/api/extensions/:providerId/repair` | Repair an extension |
| `DELETE` | `/api/extensions/:providerId` | Remove an extension |

Lifecycle routes require authentication, the global CSRF boundary, and an injected
authorizer granting the server-owned `extensions.admin` permission. Unknown actions are
not dispatched. Request bodies must be JSON objects and are bounded to 64 top-level
values.

CP-006 owns the role mapping, complete parameter allowlists, audit policy, and concrete
administrator authorization. Until that policy is installed, the default authorizer
fails closed with `authorization_unavailable`. CP-008 will connect these routes to the
extension lifecycle implementation and UI; a missing lifecycle service also fails
closed.

## Stable Errors

Errors contain a machine-readable `code` and bounded `error` message. Relevant codes
include:

- `capability_registry_unavailable`
- `capability_not_found`
- `extension_not_found`
- `authorization_unavailable`
- `extension_lifecycle_forbidden`
- `extension_lifecycle_unavailable`
- `invalid_lifecycle_action`
- `extension_lifecycle_failed`

Provider exception text, credentials, and request secrets are never included in API
errors.
