# LimeOS Integration Lifecycle IL-001 State Foundation

Date: 2026-07-20

Status: Complete; IL-002, IL-003, and IL-006 may begin

Scope: IL-001 in
`docs/plans/2026-07-20-integration-lifecycle-delivery-plan.md`

Implementation commit: `4163c30`

## Outcome

LimeOS now has a versioned, fail-closed lifecycle-state foundation for Mattermost and
AI Agents. Existing systems continue to derive state from their current configuration
and runtime when no lifecycle tombstone exists. No status read creates a lifecycle
file, and this slice adds no disable, uninstall, or purge endpoint.

The implementation consists of:

- application-owned atomic lifecycle repositories;
- lifecycle precedence and server-owned action projection;
- a Mattermost-independent AI Agents dependency snapshot;
- fixed root-helper custody for the retained Mattermost credential;
- capability adapter mappings for disabled, retained, and cleanup-required states;
- startup convergence guards in both the application and helper;
- a server-owned AI Agents feature-state input for package reconciliation;
- updater/setup migration of the fixed helper sandbox and recovery directory.

## Lifecycle Repository

`integration_lifecycle_service.py` validates tombstones against the frozen version `1`
schema before accepting or writing them. Files are regular, application-owned,
application-group-owned, and mode `0640`. Their parent must be an owned directory with
no group write or world access. Symlinked parents, symlinked records, unsafe modes,
unexpected ownership, malformed JSON, unsupported versions, unknown fields, and wrong
integration identities fail closed.

Writes use `JsonFileRepository`, which creates a same-directory temporary file, syncs
it, replaces the destination, and syncs the directory. Deletes validate the same
ownership boundary and sync the directory. Missing files return `None` without creating
the directory or a tombstone.

Lifecycle precedence is now executable:

- incomplete `running` records become `cleanup_required` and `interrupted` after a
  process restart;
- explicit cleanup failures remain `cleanup_required` and retryable;
- completed disable records produce `disabled`;
- completed Mattermost uninstall records produce `retained_data` with
  `installed: false`;
- completed agent uninstall records produce `not_installed`;
- absent records preserve legacy state derivation.

Corrupt state returns a bounded synthetic cleanup operation. Raw parse errors, paths,
record contents, and exception text do not enter public status.

## Server-Owned Actions And Dependencies

The resolver projects lifecycle actions from the frozen policy order. Mattermost purge
remains absent because its release policy is false.

Mattermost uses `AgentLifecycleSnapshotService` rather than Mattermost connectivity to
decide dependency gates. The snapshot reads only the agent tombstone, agent config, and
the two fixed unit paths:

- enabled agents block Mattermost disable and uninstall;
- disabled agents allow Mattermost disable but block uninstall;
- uninstalled agents allow both actions;
- partial, corrupt, or unreadable agent state fails closed and blocks both when those
  actions would otherwise be available.

A snapshot failure is converted to fixed cleanup-required dependency facts. Exception
text is not returned.

## Recovery Credential Custody

The helper now exposes exactly three parameter-free commands:

- `mattermost_recovery_credential_retain`
- `mattermost_recovery_credential_restore`
- `mattermost_recovery_credential_discard`

They operate only on the fixed active and recovery paths. The caller cannot supply a
path, filename, owner, mode, or content.

Credential reads use `O_NOFOLLOW`, validate the opened descriptor as a regular
mode-`0600` file, enforce a 64 KiB limit, and require root ownership for the retained
copy. Transfers create a same-directory mode-`0600` temporary destination, assign the
fixed owner, sync, replace, sync the destination directory, then unlink and sync the
source. A retry accepts an already-transferred matching copy. Conflicting copies fail
without deleting either one.

The retained directory is a real, root-owned mode-`0700` directory. Links, writable
directories, wrong ownership, unsafe files, oversized values, and unknown fields fail
with fixed messages. Public custody results contain booleans only.

## Upgrade Migration

`scripts/migrate_runtime_state.py` now:

1. creates `/var/lib/limeos/integration-recovery` through a root transient unit with
   owner `root:root` and mode `0700`;
2. installs `pihealth-helper.service.d/integration-lifecycle.conf`;
3. grants writes only to the fixed active credential and fixed recovery directory;
4. reloads systemd only when a unit or drop-in changes.

`setup.sh` contains the same fixed write paths. Its legacy recursive runtime ownership
step is followed by an explicit recovery-directory and credential ownership repair.

The normal self-updater also performs a broad legacy ownership pass. The helper now
immediately restores the recovery directory to `root:root`/`0700` and any retained
credential to `root:root`/`0600`. A link or non-regular retained credential makes the
update migration fail with a bounded ownership-repair error rather than weakening the
boundary.

No database, config rewrite, or lifecycle-file migration is required on an existing
instance.

## Startup And Package State

Application startup calls agent convergence only when the independent snapshot reports
`enabled`. Disabled, not-installed, partial, corrupt, and cleanup-required states are
left unchanged.

The helper applies a second guard: the presence of any agent lifecycle tombstone blocks
stale-runtime convergence, including a corrupt tombstone. This prevents direct or
future callers from bypassing the application guard.

The same snapshot exposes a package feature input:

| Agent state | Managed | Reconcile allowed |
| --- | --- | --- |
| Enabled | Yes | Yes |
| Disabled | Yes | Yes |
| Not installed | No | No |
| Cleanup required | No | No |

IL-003 consumes this input while changing Claude from the unconditional package
baseline to feature-scoped ownership.

## Capability Mapping

Integration adapters remain discoverable as built-in providers while their live
integration lifecycle is now authoritative inside capability status.

- Disabled integrations are disabled and unconfigured.
- Retained Mattermost data is unavailable and unconfigured, not installed or healthy.
- Cleanup-required integrations report an error with a bounded retry-cleanup issue.
- Not-installed integrations remain discoverable but unavailable and unconfigured.

The capability registry preserves this runtime lifecycle only for trusted adapter
candidates that explicitly request it. Existing storage provider candidates retain the
previous package-owned lifecycle merge.

## Verification

Focused lifecycle, helper, migration, adapter, service, package, updater, and security
run:

```text
205 passed in 7.55s
```

Full backend run:

```text
1898 passed, 1 skipped in 285.58s
```

The skip is the established hardware-dependent test. Ruff's configured `E9,F` checks,
`bash -n setup.sh`, and `git diff --check` passed. The optional local ShellCheck wrapper
could not run because `shellcheck` is not installed. No frontend files changed, so no
bundle rebuild or Playwright run was required.

## Compatibility And Rollback

Status responses gain additive lifecycle fields. Existing clients ignore them. Built-in
integration cards remain discoverable, and existing setup, repair, authentication,
alert, usage, and audit routes are unchanged.

Before any lifecycle operation exists, rollback is a normal code rollback: remove
`4163c30`, redeploy, restart the application and helper, and verify the existing
Mattermost and agent workflows. The migration-created empty recovery directory and
helper drop-in may remain safely; neither changes integration state.

Once later slices create a disable or uninstall tombstone, use the state-aware rollback
procedure from the delivery plan rather than downgrading through `cleanup_required` or
retained-data state.

## Remaining Work

- IL-002 implements Mattermost disable, enable, retained-data uninstall/reinstall,
  cleanup retry, image/orphan cleanup, and release-gated purge.
- IL-003 implements fixed agent cleanup commands and feature-scoped Claude ownership.
- IL-004 orchestrates agent uninstall and remote bot cleanup.
- IL-005 exposes secured streamed lifecycle mutations.
- IL-006 adds the shared lifecycle interface against the now-frozen status contract.
