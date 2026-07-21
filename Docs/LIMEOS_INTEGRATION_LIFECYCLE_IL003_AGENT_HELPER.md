# LimeOS Integration Lifecycle IL-003 Agent Helper

Date: 2026-07-20

Status: Complete; the local AI Agents cleanup boundary is ready for IL-004 orchestration

Scope: IL-003 in
`docs/plans/2026-07-20-integration-lifecycle-delivery-plan.md`

Implementation commit: `2206cb5`

## Outcome

The privileged helper now exposes one fixed local uninstall command:

```text
agent_runtime_uninstall {"remove_claude_code": <boolean>}
```

The command rejects a missing choice, non-Boolean value, or any additional field. No
caller can supply a unit, path, package, source, signing key, user, or group. This slice
adds no route or UI control; IL-004 will own the lifecycle tombstone and invoke this
helper boundary.

Claude Code is no longer an unconditional host-baseline package. The shipped manifest
marks it as owned by the `ai_agents` feature, while `python3-psutil` and
`unattended-upgrades` remain host baseline packages.

## Fixed Cleanup Boundary

Cleanup runs ordered, idempotent steps and reports each step's `success`, `changed`, and
`skipped` state. A failure returns the bounded `failed_step`; retry starts the same fixed
sequence, where already-absent resources report `changed: false`.

The helper performs these required local steps:

1. stop and disable `limeos-agent.service` and `limeopsd.service`;
2. remove their two fixed unit files and reload systemd;
3. remove the three fixed agent configuration files;
4. remove only the agent library, state, Claude credentials, isolated virtual
   environment, and LimeOps state directories;
5. either retain all Claude package artifacts or remove the fixed apt hold, package,
   source, and signing key.

Directory cleanup rejects substituted symlinks and unsupported filesystem objects. It
does not remove the `lime-agent`, `limeops`, or `limeops-client` users and groups. It
also leaves the agent audit log, Mattermost stack and data, Mattermost bot cleanup,
alerts, package-update channel configuration, and unrelated provider state outside the
helper boundary.

When `remove_claude_code` is false, the installed package, hold, apt source, and signing
key are not queried or changed. They become user-retained state rather than a LimeOS
global desired package.

## Feature-Scoped Reconciliation

Package ownership is derived from fixed server lifecycle and runtime facts, never from
the package command request:

- a valid installed legacy runtime or completed disabled state manages Claude;
- a completed `not_installed` state excludes Claude;
- running cleanup, `cleanup_required`, incomplete runtime, corrupt state, unsafe state,
  and an uninstalled host all exclude Claude;
- setup still uses the explicit fixed provider installer and returns Claude to normal
  feature management once lifecycle setup completes.

The same filter is applied to manual package check/apply, pending held updates, approval
application, nightly critical holds, nightly update reporting, and nightly reconciliation.
The self-update agent refresh is also blocked while feature reconciliation is not
allowed, so it cannot recreate runtime files before the package filter runs. Startup
convergence retains the IL-001 tombstone guard.

Both uninstall choices therefore remain stable under manual reconcile, nightly jobs,
application restart, and LimeOS self-update. Retained Claude is neither upgraded,
removed, held again, nor reported as globally managed. Removed Claude is not
reinstalled.

## Compatibility And Deployment

No database, config-file, or one-time migration is required. Existing installed agents
remain managed when the fixed agent unit, broker unit, and valid settings file are
present. Hosts that never installed AI Agents stop receiving Claude through the global
package baseline. Existing package approval records may remain on disk but cannot be
applied while the owning feature is excluded.

The update must deploy the manifest, manifest schema, package model, and helper together.
The agent runtime installer already copies the package model and manifest into the fixed
broker library when setup or repair runs.

Rollback before any lifecycle action is a normal code rollback. After uninstall begins,
do not downgrade to a pre-IL-003 release: its unconditional manifest can manage or
reinstall Claude despite the lifecycle tombstone. Complete cleanup or reinstall AI
Agents under lifecycle-aware code before considering rollback.

## IL-004 Handoff

IL-004 must write the application-owned lifecycle tombstone before invoking
`agent_runtime_uninstall`. It should pass only the recorded Boolean choice, treat a
failed helper step as required local cleanup failure, and expose Retry cleanup without
inventing caller-controlled paths or partial cleanup parameters.

The helper owns local cleanup only. IL-004 remains responsible for remote Mattermost bot
cleanup, its bounded warning behavior, lifecycle checkpoints, operation streaming, and
final tombstone state. A remote bot failure may complete with the frozen warning only
after this required local helper command succeeds.

## Verification

Focused package, reconciliation, provisioning, nightly, and lifecycle helper tests:

```text
100 passed in 0.31s
```

Independent full repository Python run:

```text
1940 passed, 1 skipped in 300.76s
```

The mandatory implementation commit gate passed:

```text
1799 passed, 1 skipped, 141 deselected in 80.87s
141 Playwright tests passed in 231.64s
tox -e all: OK
```

Repository Ruff `E9,F`, focused Ruff checks, Python compilation, and
`git diff --check` passed. Tests cover both Claude choices, exact parameter rejection,
fixed path removal, audit and Mattermost preservation, symlink rejection, retry after an
independent cleanup failure, installed/disabled/uninstalled/corrupt lifecycle states,
manual reconciliation, pending updates, nightly holds/reporting, and updater blocking.

## Remaining Work

- IL-004 orchestrates AI Agents lifecycle state, remote bot cleanup, warnings, and retry.
- IL-005 exposes the lifecycle services through secured owner-bound operations.
- IL-006 supplies the shared lifecycle dialog and invalidation behavior.
- IL-007 adds AI Agents lifecycle controls after the backend and shared UI are available.
