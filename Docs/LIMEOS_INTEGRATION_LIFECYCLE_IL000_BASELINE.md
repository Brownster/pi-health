# LimeOS Integration Lifecycle IL-000 Baseline

Date: 2026-07-20

Status: Complete; IL-001 may begin

Scope: IL-000 in
`docs/plans/2026-07-20-integration-lifecycle-delivery-plan.md`

Implementation commit: `94d6ae7`

## Decision

Proceed with lifecycle repositories and state derivation against the version `1`
contracts in:

- `config/integration-lifecycle.json`
- `config/schemas/integration-lifecycle-status.schema.json`
- `config/schemas/integration-lifecycle-tombstone.schema.json`

This slice adds no disable, uninstall, or purge behavior. Existing installations keep
their current status and setup behavior. A lifecycle tombstone must not be created
until a later lifecycle mutation starts.

## Current Behavior

### Mattermost

`MattermostIntegrationService.status()` currently derives installation from
`mattermost.json` and reports `connected`, `degraded`, `disconnected`, or
`not_installed`. Setup writes the active configuration and root-sensitive environment,
generates the Compose stack, starts Postgres and Mattermost, configures the team and
channels, builds alertd, and starts alert delivery.

There is no current disable, enable, uninstall, retained-data, cleanup-retry, or purge
operation. The current status response does not expose server-owned lifecycle actions.

### AI Agents

`AgentIntegrationService.status()` combines Mattermost status with the privileged
runtime snapshot. It reports `connected`, `degraded`, `disconnected`, `disabled`,
`authenticating`, `setup_required`, or `not_installed`. Disable is currently a
synchronous helper call; setup, repair, and authentication use operation streams.

There is no current uninstall or cleanup-retry operation. Startup convergence can
currently repair stale agent state and does not yet recognize a lifecycle tombstone.

### Packages

`config/limeos-packages.json` currently declares `claude-code` as an unconditional
pinned package. All reconciliation paths therefore consider Claude part of the global
host baseline. IL-003 must make it AI Agents feature-scoped before agent uninstall can
be released.

## Frozen Public Contract

Both integration status responses will add these required top-level facts:

| Field | Contract |
| --- | --- |
| `state` | One versioned lifecycle state from the precedence below |
| `installed` | Runtime or managed stack is installed |
| `retained_data` | Integration is uninstalled while declared user data remains |
| `cleanup_required` | Required cleanup failed or was interrupted |
| `allowed_actions` | Ordered server-owned action allowlist |
| `blocked_actions` | Bounded dependency facts, not inferred client-side |
| `cleanup_operation` | Secret-free running, failed, or interrupted operation summary |
| `warnings` | Stable code and bounded message pairs |

State precedence is:

1. `cleanup_required`
2. `retained_data`
3. `not_installed`
4. `disabled`
5. `authenticating`
6. `setup_required`
7. `disconnected`
8. `degraded`
9. `connected`

`installed`, `retained_data`, and `cleanup_required` are independent facts. In
particular, retained Mattermost data is not an installed stack, while partially cleaned
state may retain some installed resources and still be `cleanup_required`.

The global action order is `setup`, `enable`, `repair`, `authenticate`, `disable`,
`uninstall`, `retry_cleanup`, then `purge`. Mattermost does not declare
`authenticate`; AI Agents does not declare `purge`. The client may show only known
actions returned by the server in this order.

The only initial dependency blockers are:

| Code | Blocked action | Required action | Route |
| --- | --- | --- | --- |
| `agents_must_be_disabled` | Mattermost disable | Disable AI Agents | `/integrations#ai-agents` |
| `agents_must_be_uninstalled` | Mattermost uninstall | Uninstall AI Agents | `/integrations#ai-agents` |

The internal route is fixed. Client implementations must keep external, absolute,
malformed, noncanonical, and unknown anchors inert.

The initial warning catalog contains `agent_bot_cleanup_failed`. Its message states
that local agent removal completed but remote Mattermost bot cleanup did not. Required
local cleanup failures are errors and enter `cleanup_required`; they are not warnings.

## Tombstone Contract

Lifecycle records use schema version `1` and live at:

- `/var/lib/limeos/integrations/mattermost-lifecycle.json`
- `/var/lib/limeos/integrations/agents-lifecycle.json`

The application service owns these files at mode `0640` under an application-owned
mode-`0750` directory. Writes use a temporary file in the same directory, file sync,
atomic replacement, and directory sync. Records contain only the integration, action,
target state, operation ID, timestamps, completed fixed steps, retained-data fact,
Claude removal choice, bounded failure, and warning codes.

Missing records use legacy state derivation. Invalid JSON, unsupported versions,
invalid fields, invalid modes, unexpected ownership, and corrupt records fail closed as
`cleanup_required`; they never fall back to connected or not installed.

Records are created only after a secured lifecycle operation has acquired its operation
slot. Successful enable removes the disable record. Successful Mattermost purge removes
the retained-data record. Completed disable and uninstall records remain so startup and
package reconciliation cannot recreate or start removed resources. Required cleanup
failure retains the record for retry.

## Recovery Credential Custody

Mattermost retained-data reinstall requires the original database credential. The
unprivileged application never reads or transports that value.

The active credential is `/etc/limeos/integrations/mattermost.env`. The retained copy is
`/var/lib/limeos/integration-recovery/mattermost.env`, held under a root-owned
mode-`0700` directory as a root-owned mode-`0600` file.

Only these parameter-free helper commands may transfer it:

- `mattermost_recovery_credential_retain`
- `mattermost_recovery_credential_restore`
- `mattermost_recovery_credential_discard`

Each transfer writes a temporary destination on the destination filesystem, syncs it,
sets ownership and mode, atomically replaces the destination, syncs its directory, and
only then unlinks the source. A failed source unlink can leave two protected copies but
cannot leave zero. Retry resolves that state idempotently. Public results contain only
success and retained/restored/discarded booleans; they never contain content or a path.

IL-001 implements and tests this helper boundary before a lifecycle service consumes
it.

## Owned Resources

### Mattermost

LimeOS owns the `mattermost` Compose project, the three fixed containers
`limeos-mattermost-db`, `limeos-mattermost`, and `limeos-alertd`, and the two local
images `limeos/mattermost-team:11.8.3-arm64` and `limeos/alertd:local`.

The declared logical data volumes are:

- `mattermost-postgres`
- `mattermost-config`
- `mattermost-data`
- `mattermost-logs`
- `mattermost-plugins`

The active config, secret, alert status/history, generated stack directory, stack
notification hook, and package update hook are managed integration resources. Uninstall
removes or disconnects these active resources while preserving all five logical volumes
and the recovery credential.

The upstream Postgres image, external volumes, bind mounts, and caller-selected storage
are never deletion targets. Purge remains release-disabled and absent from
`allowed_actions` until IL-010 supplies destructive target evidence.

### AI Agents

LimeOS owns the `limeos-agent.service` and `limeopsd.service` units; agent configuration,
secret reference, and policy files; installed runtime library; agent state and Claude
credentials; agent virtual environment; and LimeOps runtime state.

The optional Claude cleanup boundary is exactly the `claude-code` package, its LimeOS
APT source, its signing key, and its LimeOS-managed hold. Removal defaults on. Keeping
Claude leaves those resources untouched and outside subsequent global reconciliation.

The agent security audit at `/var/log/limeos/agent-audit.jsonl`, all system users and
groups, Mattermost and alert data, and unrelated provider configuration are preserved.

## API And Security Contract

Lifecycle mutations use authenticated, CSRF-protected, `extensions.admin`-authorized,
owner-bound streamed operations. Unknown request fields fail before a helper or Compose
call. Requests contain choices and confirmations only; callers cannot provide paths,
units, packages, images, containers, projects, or volume names.

Public status, operation events, errors, warnings, audit records, and logs use stable,
bounded facts. Raw exceptions, command output, paths, credentials, tokens, webhooks,
DSNs, environment values, and authorization headers are not public output.

The fixed mutation routes remain those listed in the delivery plan. IL-005 converts the
existing synchronous agent disable route in the same commit that updates its client.

## Compatibility And Rollback

Existing installed and uninstalled systems require no migration. Until a lifecycle
operation starts, the absence of a tombstone preserves current state derivation.

Code rollback is safe while the system remains in a pre-lifecycle state. After a
disable, retained-data uninstall, agent uninstall, or cleanup failure, the integration
must first be restored to an installed, enabled, clean state with the lifecycle-aware
version. Permanent Mattermost purge requires backup restoration; code rollback cannot
restore deleted data.

## Verification

Focused integration contract and compatibility run:

```text
70 passed in 1.26s
```

Full backend run:

```text
1866 passed, 1 skipped in 301.42s
```

The skip is the established hardware-dependent test. No frontend files changed, so the
Playwright suite was not required for this baseline-only slice. `git diff --check`
passed before the implementation commit.

## IL-001 Entry Conditions

- Consume the frozen policy rather than duplicating paths or action order.
- Implement atomic lifecycle repositories without creating files during ordinary
  status reads.
- Derive legacy state when records are absent and fail closed for corrupt records.
- Implement helper-only recovery credential custody and its runtime sandbox migration.
- Add Mattermost-independent agent state for dependency checks.
- Map disabled, retained-data, and cleanup-required states through capability adapters.
- Prevent startup convergence from changing `cleanup_required` or uninstalled agents.
