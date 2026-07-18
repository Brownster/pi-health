# LimeOS Capability Providers CP-009 Route Compatibility

Date: 2026-07-18

Status: Implemented

Scope: CP-009 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

## Route Contract

The frontend now owns one canonical path contract for Settings, Extensions, Pools, and
the legacy Plugins surface. Extension detail links use a shared path builder that safely
encodes provider IDs, so direct links and browser reloads retain the selected extension.

The stable extension routes are:

- `/settings/extensions` for the installed-extension index
- `/settings/extensions/:id` for package details and administration

Settings and Extensions share a restrained Settings context navigation. It identifies
Extensions as an Advanced administration surface while preserving the primary Settings
navigation state on index and detail routes.

## Plugins Compatibility

CP-009 prepares the legacy route cutover but does not activate it. `/plugins` remains an
operational route and its primary-navigation entry remains available while the current
Pools and protection workflows still depend on it.

The compatibility contract records `/settings/extensions` as the future redirect target
with redirect enablement set to false. CP-019 activates the redirect and removes Plugins
from primary navigation only after the Pools and Protection domain pages own their full
workflows.

This keeps existing bookmarks and operational paths stable during the additive provider
migration.

## Existing-Instance Deployment

No manual migration is required for Holly or another existing installation:

1. Use the normal LimeOS update workflow.
2. Allow the updater to restart the application and helper services.
3. Hard refresh the browser so it loads the committed CP-009 bundle.
4. Confirm Settings > Advanced > Extensions opens and a detail URL survives reload.
5. Confirm Plugins and existing Pools, protection, Mattermost, alerting, and AI Agent
   workflows remain available.

There is no database, manifest, plugin configuration, or API migration. Existing provider
IDs and stored paths remain unchanged, and the target Pi does not need npm because the
production frontend bundle is committed.

## Verification

- Route contract tests: 2 passed
- Extension presentation tests: 4 passed
- Focused Extensions, Settings, and storage browser suite: 33 passed
- Full non-browser suite: 1,663 passed, 1 skipped
- Full browser parity suite: 134 passed
- Ruff, TypeScript, production bundle freshness, responsive overflow, visual inspection,
  and `git diff --check`: passed

Desktop and phone screenshots were inspected at 1440 x 1000 and 390 x 844. Settings
context navigation and extension content remain readable without overlap or horizontal
overflow.
