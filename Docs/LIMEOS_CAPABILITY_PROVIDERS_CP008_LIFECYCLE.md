# LimeOS Capability Providers CP-008 Lifecycle Controls

Date: 2026-07-17

Status: Implemented

Scope: CP-008 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

## Lifecycle Service

The capability API now uses a default lifecycle service backed by the existing
`plugin_manager`. It does not introduce a second package database or configuration
format.

Supported operations are:

- Install a reviewed GitHub provider in a disabled state
- Enable or disable an installed provider
- Update a managed GitHub checkout from its configured source
- Repair a missing or damaged managed GitHub checkout
- Remove a disabled third-party provider

Built-in providers remain part of the LimeOS release and expose only enable or disable.
Integration adapters remain managed from their owning Integrations page. Pip installation
continues to fail closed because it would execute package setup code as root.

Every successful install, enable, disable, update, or repair response reports that an
application restart is required. Provider code is loaded at startup; the lifecycle
service does not hot-load Python modules into the running process.

## Administration UI

Sessions with `extensions.admin` receive an Install action on the extension index and
state-appropriate actions on extension details. Viewer and operator sessions see package
status without mutation controls.

The UI provides:

- A source trust warning before GitHub installation
- Explicit confirmation for every lifecycle mutation
- A typed extension-ID confirmation before removal
- A disabled Remove action until the provider is disabled
- Pending, success, and bounded failure states
- Restart guidance after operations that change loaded provider code or state

Normal provider configuration remains on its owning Pools, Protection, Mounts, Shares,
or Integrations surface.

## Safety Boundary

The CP-006 administrator, CSRF, validation, redaction, and audit controls remain the HTTP
security boundary. CP-008 adds one non-blocking lifecycle lock in the application and
registers all plugin package mutations with the helper's shared mutation lock.

GitHub update and repair operations fetch the source recorded in `plugins.json`, inspect
the fetched manifest before checkout reset, and require its ID to match the managed
directory. Install and repair remove a newly cloned directory when manifest identity
validation fails. Update refreshes package metadata while preserving enablement and
unrecognized existing metadata fields.

## Existing-Instance Deployment

No manual migration is required for Holly or another existing installation:

1. Use the normal LimeOS update workflow.
2. Allow the updater to apply its standard runtime step and restart the application and
   helper services.
3. Hard refresh the browser so it loads the committed CP-008 bundle.
4. Confirm the existing Plugins page, Pools configuration, mounts, shares, Mattermost,
   alerts, and AI Agent remain unchanged.
5. Confirm Settings > Advanced > Extensions loads. Registry-backed package controls
   appear as the provider adapters are delivered in later slices.

There is no database migration, no `plugins.json` conversion, and no need to reinstall a
provider or recreate MergerFS, SnapRAID, Mattermost, or agent configuration. The existing
plugin file remains authoritative and is read in place.

Reverting the CP-008 commits is sufficient to roll back LimeOS because the stored format
is unchanged. A third-party package explicitly updated through the new UI is a separate
package-code change; record its revision before testing Update if that checkout must also
be rolled back.

## Verification

- Focused lifecycle, API, plugin-manager, and helper suite: 140 passed
- Extension presentation tests: 4 passed
- Focused Extensions and Settings browser suite: 16 passed
- Full non-browser suite: 1,661 passed, 1 skipped
- Full browser parity suite: 133 passed
- Ruff, TypeScript, bundle freshness, responsive overflow, visual inspection, and
  `git diff --check`: passed

Desktop extension administration and the phone install dialog were inspected at
1440 x 1000 and 390 x 844.
