# LimeOS Capability Providers CP-020 Cross-Domain Hardening

Date: 2026-07-18

Status: Implemented

Runtime commit: `a18627b`

Scope: CP-020 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

## Release Gate

CP-020 audited the completed Disks, Extensions, Pools, Protection, and Integrations
surfaces as one release boundary. The gate covered accessibility, responsive layout,
partial-failure recovery, existing-instance compatibility, provider security, and the
committed frontend bundle.

The audit found and corrected these concrete gaps:

- MergerFS, SnapRAID, and AI Agent tablists now support Left, Right, Up, Down, Home, and
  End keys with automatic activation, one tab stop, and complete tab/panel relationships.
- The Extensions list now reports `capabilities available`. It no longer describes an
  installed but unconfigured provider as `ready`.
- Generic setup controls now have stable names and move focus to the first local or
  server-reported invalid field.
- AI Agent credentials, limits, repair, and authorization controls now have stable form
  names while preserving browser credential semantics.
- Loading copy on the affected provider surfaces uses a consistent ellipsis.

Existing modal behavior already met the gate: dialogs move and trap focus, close with
Escape, lock background scrolling, and restore focus to their trigger. Existing error
regions remain announced, preserve bounded public guidance, and retain in-place retry or
refresh paths.

## Security And Compatibility

The hardening slice does not expand provider trust or runtime permissions:

- manifests remain declarative and cannot load provider JavaScript, HTML, remote assets,
  Python entry points for integration adapters, or unregistered tailored renderers;
- lifecycle changes remain authenticated, CSRF-protected, administrator-owned, bounded
  by fixed parameters, redacted, and audited;
- generic actions remain limited to declared catalogs and mutating actions require
  confirmation;
- registry, adapter, status, and provider failures remain isolated from healthy domains;
- MergerFS, SnapRAID, Mattermost, and AI Agents retain their existing configuration,
  runtime paths, APIs, and owning operational pages.

No database, manifest, provider, plugin, or configuration migration is introduced. The
published frontend bundle is committed and source-digest checked, so target systems do
not need Node or npm.

## Verification

- Full non-E2E suite: 1,690 passed, 1 skipped
- Full Playwright suite: 141 passed
- Capability contract, registry, security, storage adapter, and integration adapter
  release subset: 73 passed
- Frontend TypeScript and capability/extension contracts: passed
- Focused keyboard and responsive browser cases: 8 passed across desktop, tablet, and
  phone where parameterized
- Production build and committed bundle source digest: passed
- Frontend interaction anti-pattern scan and `git diff --check`: passed
- Desktop 1440 x 1000 and phone 390 x 844 screenshots: inspected with no overflow or
  browser console errors

The Vite build continues to report the existing main-chunk size warning. CP-020 does not
add continuous polling, background collection, provider runtime calls, or target-Pi
overhead.

## Deployment And Rollback

Deploy CP-020 through the normal LimeOS updater, restart the application, and hard reload
the browser. No migration or manual provider repair is required. A target Pi without npm
uses the committed bundle as intended.

Rollback is the reverse code deployment to the previous committed bundle. Do not delete
or recreate provider configuration. CP-021 records Holly preflight state, deployed
revision, workflow evidence, and a tested rollback result before release signoff.
