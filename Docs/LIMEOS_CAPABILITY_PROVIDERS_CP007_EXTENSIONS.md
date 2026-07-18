# LimeOS Capability Providers CP-007 Extensions Surface

Date: 2026-07-17

Status: Implemented

Scope: CP-007 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

## User Surface

Settings now includes an Advanced section linking to the read-only Extensions surface.
The authenticated route contract is:

- `/settings/extensions` for the installed-extension index
- `/settings/extensions/:id` for one extension's package and capability details

The index groups packages by their primary capability and shows name, description,
version, source, compatibility, provider health, and operational-provider count. Registry
diagnostics appear above the list without preventing valid packages from rendering.
Loading, unavailable, and no-provider states remain bounded and actionable.

The detail route shows package source, version, runtime, compatibility, contract state,
enablement, health, update state, and declared capabilities. Capability rows link to an
existing owning page when LimeOS has one. Capabilities without an owning page state that
the page is not available yet instead of linking to an unrelated workflow.

## Security and Lifecycle Boundary

CP-007 was inspection-only. CP-008 now owns install, update, enable, disable, repair, and
removal controls with confirmation flows. The server-side CP-006 authorization policy
remains the enforcement boundary for extension reads and mutations.

The shell now displays the authenticated user's server-provided role. CP-009 prepares
the route compatibility contract, but the legacy `/plugins` route and primary-navigation
entry remain unchanged until CP-019 activates the final navigation migration after the
Pools and Protection domain pages are complete.

## Compatibility

The frontend consumes the additive CP-004 extension index and detail contracts. An empty
production registry renders a focused discovery state, so this slice remains deployable
before the MergerFS, SnapRAID, and integration adapters arrive.

The production frontend bundle is committed. Updating a target Pi does not require npm
or a frontend build.

## Verification

- Extension grouping and presentation unit tests: 3 passed
- Existing generic capability-renderer tests: 8 passed
- Focused Extensions and Settings browser tests: 11 passed
- Full non-browser suite: 1,646 passed, 1 skipped
- Full browser parity suite: 128 passed
- TypeScript checks, production bundle freshness, responsive overflow checks, and
  `git diff --check`: passed

Desktop and phone screenshots were inspected at 1440 x 1000 and 390 x 844. The page
retains the existing dense LimeOS operations layout without horizontal overflow.
