# LimeOS Capability Providers CP-019 Navigation Cutover

Date: 2026-07-18

Status: Implemented

Runtime commit: `381f852`

Scope: CP-019 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

## Final Navigation

The primary navigation now reflects the accepted product model:

- Pools owns storage pooling providers and configured pools.
- Protection owns parity and other protection providers.
- Integrations owns external connections, alert policy, and AI Agents.
- Settings / Advanced / Extensions owns package discovery, compatibility, diagnostics,
  source, version, and lifecycle administration.
- Plugins no longer appears in the desktop sidebar or mobile drawer.

Settings remains the active primary destination on the Extensions index and detail pages.
The local Settings navigation keeps Overview and Extensions visible as peer sections under
the Advanced context.

## Compatibility Redirects

The authenticated SPA route `/v2/plugins` now performs a replace redirect to
`/v2/settings/extensions`. This preserves old browser bookmarks without leaving the
obsolete route in browser history.

Server-owned legacy HTML bookmarks now resolve as follows:

| Legacy path | Destination |
| --- | --- |
| `/plugins.html` | `/v2/settings/extensions` |
| `/storage.html` | `/v2/settings/extensions` |
| `/pools.html` | `/v2/pools` |
| `/protection.html` | `/v2/protection` |

Extension capability links now open Protection as well as Pools, Mounts, Shares, and
Integrations. Provider configuration links no longer fall back to `/plugins`; package
administration resolves through the matching extension detail route.

## Compatibility Boundary

CP-019 changes navigation ownership, not provider storage or operations:

- `/api/storage/plugins/*` remains available for the tailored MergerFS and SnapRAID
  compatibility adapters.
- Existing provider IDs, `plugins.json`, MergerFS pools, SnapRAID assignments, schedules,
  state, logs, generated configuration, mounts, and shares remain unchanged.
- The legacy `StoragePage` source remains in the repository for the current rollback
  boundary, but it is no longer reachable through the route table.
- Pools, Protection, and Extensions retain their existing partial-failure recovery paths.

Legacy Plugins browser tests were retired with the unreachable page. Equivalent supported
coverage remains in Extensions lifecycle tests, Pools/MergerFS tests,
Protection/SnapRAID tests, and storage API tests.

## Existing-Instance Deployment

No database, manifest, plugin, provider, or configuration migration is required:

1. Use the normal LimeOS updater and allow the application to restart.
2. Hard reload the browser so it loads the committed CP-019 bundle.
3. Open an existing `/v2/plugins` or `/plugins.html` bookmark and confirm it resolves to
   Settings / Advanced / Extensions.
4. Confirm Plugins is absent from both the desktop sidebar and mobile drawer.
5. Confirm Pools and Protection still open the existing MergerFS and SnapRAID
   configuration and operation workspaces.
6. Confirm Mattermost alerts and AI Agent responses remain operational.

The production bundle is committed, so a target Pi does not need Node or npm. Rollback is
the reverse code deployment: revert the CP-019 runtime commit and redeploy its previous
committed bundle. Do not delete or recreate provider configuration.

## Verification

- Full non-E2E suite: 1,690 passed, 1 skipped
- Backend route and application suite: 66 passed, 1 skipped
- Frontend capability, extension, Pools, Protection, route, and disk contracts: 11 passed
- Focused navigation, Extensions, Settings, Pools, and Protection Playwright suite:
  38 passed across desktop, tablet, and phone profiles where parameterized
- Full Playwright suite: 141 passed
- TypeScript, Ruff, production build, bundle freshness, responsive overflow, browser
  console checks, and `git diff --check`: passed
- Desktop 1440 x 1000 and phone 390 x 844 screenshots: inspected

CP-020 owns cross-domain accessibility, responsive, recovery, compatibility, and security
hardening. CP-021 records the Holly upgrade and rollback evidence after that gate passes.
