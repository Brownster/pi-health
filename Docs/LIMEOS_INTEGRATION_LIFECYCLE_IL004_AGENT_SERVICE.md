# LimeOS Integration Lifecycle IL-004 Agent Service

Date: 2026-07-21

Status: Complete; AI Agents lifecycle orchestration is ready for IL-005 APIs

Scope: IL-004 in
`docs/plans/2026-07-20-integration-lifecycle-delivery-plan.md`

Implementation commit: `0b18b1c`

## Outcome

`AgentIntegrationService` now owns resumable disable and uninstall workflows. It writes
the application-owned agent tombstone before a mutating helper call, records each
completed orchestration step, and retains `cleanup_required` after required local
failure. Retry reuses the recorded Claude removal choice and skips completed destructive
steps.

This slice adds service methods only. IL-005 will expose them through authenticated,
owner-bound streamed operations; IL-007 will add their management dialogs.

## Lifecycle Operations

Disable records target state `disabled`, invokes only `agent_runtime_disable`, and
leaves Mattermost and alert delivery active. A failed disable retains the tombstone and
can be retried idempotently.

Uninstall records target state `not_installed` and the Boolean
`remove_claude_code` choice. It runs two application checkpoints in order:

1. delete the fixed Mattermost bot account with fresh write-only administrator
   credentials;
2. invoke `agent_runtime_uninstall` with only the recorded Boolean choice.

The local helper remains responsible for removing the fixed services, configuration,
credentials, runtime state, usage state, and optional Claude package artifacts defined
by IL-003. Setup and successful repair delete a completed disabled or uninstalled
tombstone, returning the feature to normal package ownership.

## Failure And Recovery

Remote bot cleanup is best effort. A login, connectivity, lookup, or delete failure is
not exposed and does not block required local cleanup. Only after local cleanup succeeds
does the operation complete with the frozen `agent_bot_cleanup_failed` warning.

Required local failure returns the bounded public message and stores
`agent_<action>_failed`. Retry assigns a fresh operation identifier, preserves the
original removal choice and warnings, and skips every completed checkpoint. Remote bot
deletion also treats HTTP 404 as success, making crash recovery safe if deletion
succeeded before its checkpoint was persisted.

Mattermost administrator passwords and session tokens are never written to the
tombstone, operation events, helper parameters, or public errors. Retry accepts fresh
credentials rather than recovering them from application state.

## Ownership Boundary

The helper status response now includes the non-secret configured bot user identifier,
which is validated before it becomes a Mattermost API path. Callers still cannot supply
a user identifier, path, unit, package, or cleanup step.

Agent lifecycle status is authoritative even when Mattermost status is unavailable.
When Mattermost is reachable, its non-secret site, team, and channel metadata remains
visible on disabled and uninstalled agent cards. The independent agent lifecycle
snapshot used by Mattermost dependency checks remains Mattermost-free.

The orchestration does not remove the agent audit log, Mattermost data or alerts,
Mattermost configuration, system users or groups, or unrelated provider state. Those
boundaries are enforced by the IL-003 helper allowlists and their tests.

## Compatibility And Deployment

No database, configuration, or one-time migration is required. Existing installations
without a tombstone continue to use runtime-derived state. New tombstones are created
only when a lifecycle operation starts.

The application, helper, lifecycle policy/schema, and IL-003 package ownership changes
must be deployed together before the new routes are enabled. A completed uninstall
tombstone intentionally keeps Claude outside reconciliation whether the package was
removed or retained. Successful setup removes that tombstone and resumes feature
ownership.

Rollback is straightforward before a lifecycle action begins. After disable or
uninstall starts, complete or retry the action with lifecycle-aware code before rolling
back to a release that does not understand the tombstone.

## Verification

Focused lifecycle, transport, helper, contract, API, and adapter tests:

```text
107 passed in 2.79s
```

Broader agent, Mattermost, package, provisioning, and lifecycle service tests:

```text
227 passed in 4.70s
```

The mandatory implementation commit gate passed:

```text
1810 passed, 1 skipped, 141 deselected in 72.97s
141 Playwright tests passed in 224.04s
tox -e all: OK
```

Repository Ruff `E9,F`, focused Ruff checks, Python compilation, and
`git diff --check` passed. Tests cover both Claude choices, tombstone-before-helper
ordering, disable recovery, bot deletion and 404 idempotence, bounded remote warnings,
local cleanup failure, checkpoint skipping, fresh retry credentials, secret redaction,
uninstall from disabled state, setup re-entry, and Mattermost-independent status.

## Remaining Work

- IL-005 exposes the lifecycle services through strict secured streamed operations.
- IL-006 supplies the shared lifecycle dialog and cross-card invalidation behavior.
- IL-007 adds AI Agents disable, enable/repair, uninstall, warning, and retry controls.
