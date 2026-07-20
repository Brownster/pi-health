# LimeOS Integration Lifecycle IL-002 Mattermost Service

Date: 2026-07-20

Status: Complete; the Mattermost service boundary is ready for IL-005 APIs and IL-008 UI

Scope: IL-002 in
`docs/plans/2026-07-20-integration-lifecycle-delivery-plan.md`

Implementation commit: `56e6362`

## Outcome

The Mattermost integration service now implements dependency-gated disable, enable,
retained-data uninstall, retained-data reinstall, cleanup retry, and release-gated data
purge. This slice exposes no new route or UI control. IL-005 will authorize and stream
these service methods, and IL-008 will present them to administrators.

Every lifecycle mutation writes the version `1` tombstone before changing runtime
state. Each fixed step is checkpointed after success. A local failure changes the phase
to `cleanup_required` with a bounded public message; a retry resumes only the remaining
steps. A `running` record left by a process restart is handled through the same retry
path.

## Disable And Enable

Mattermost disable first reads the Mattermost-independent AI Agents snapshot. Enabled
agents block disable with a direct, bounded instruction to disable AI Agents. LimeOS
does not cascade the dependency action.

Disable runs Compose `down --remove-orphans` for the stored stack. It stops and removes
the Mattermost, Postgres, and alert containers while preserving:

- the generated stack and Compose file;
- the active integration configuration and secrets;
- alert policy and notification-hook configuration;
- all named Mattermost volumes and chat data.

Enable starts the full stack with Compose `up -d`, waits for the Mattermost API, and
deletes the disable tombstone only after readiness succeeds. An interrupted readiness
check retains the completed start checkpoint, so retry verifies the existing start
instead of repeating it.

## Retained-Data Uninstall And Reinstall

Mattermost uninstall requires AI Agents to be uninstalled, not merely disabled. Before
removal it verifies the generated Compose storage layout against the fixed LimeOS
project and logical-volume contract. An edited project name, unexpected service,
external volume definition, bind-mounted database or application data, symlink, or
unknown layout fails closed before containers or credentials are removed.

Successful uninstall performs fixed, independently checkpointed steps:

1. verify the generated storage layout;
2. run Compose `down --remove-orphans` without `-v` or `--volumes`;
3. move the database credential into root-helper recovery custody;
4. remove stack-notification and package-update hook configuration;
5. remove local Mattermost status and alert history;
6. remove active integration configuration and generated stack files;
7. remove only `limeos/mattermost-team:11.8.3-arm64` and
   `limeos/alertd:local`.

Postgres and every declared Mattermost volume remain. The public state becomes
`retained_data`, with normal setup available for reinstallation.

Retained-data setup restores the protected credential before generating the stack. The
installer reuses the original `POSTGRES_PASSWORD`, creates fresh webhook configuration,
and deletes the tombstone only after Mattermost, alert delivery, and the test alert are
ready. The recovery transfer is idempotent, so a failed setup can be submitted again
without generating a password that no longer matches Postgres.

## Purge Boundary

Purge remains disabled by the server-owned release policy. It is absent from
`allowed_actions`, and a direct service call stops before Docker or recovery custody is
touched.

When a later release explicitly enables it, purge accepts no project, image, volume, or
path from a caller. It resolves the five fixed logical volumes under the fixed
`mattermost` Compose project, requires the complete expected set, rejects unknown
project volumes, and inspects both Compose ownership labels. Each individual removal
rechecks those labels immediately before deletion, including after a resumed cleanup.
Missing or changed labels fail closed with bounded manual guidance. The recovery
credential is discarded only after every verified volume is absent.

## Status And Compatibility

The IL-001 resolver remains authoritative for lifecycle state:

- completed disable reports `disabled`;
- completed uninstall reports `retained_data` and `installed: false`;
- incomplete or failed work reports `cleanup_required` with only `retry_cleanup`;
- verified enable and purge delete their tombstones and return status to legacy facts.

Existing Mattermost installations require no config or database migration. No
tombstone is created until an administrator starts a future lifecycle action. The
application factory now shares one validated lifecycle repository and policy between
status and mutation handling, and supplies the existing fixed helper custody client.

Rollback before any lifecycle action is a normal code rollback. After disable,
uninstall, or cleanup failure, do not downgrade past the lifecycle-aware release until
the operation is completed or reversed. Purge is irreversible but remains unavailable
in this release.

## Verification

Focused Mattermost lifecycle, lifecycle-state, contract, and application tests:

```text
138 passed, 1 skipped in 11.07s
```

Final focused lifecycle run:

```text
73 passed in 1.73s
```

Full repository Python run:

```text
1928 passed, 1 skipped in 286.62s
```

The mandatory commit gate also passed:

```text
1787 passed, 1 skipped, 141 deselected in 74.31s
141 Playwright tests passed in 206.44s
tox -e all: OK
```

Repository-wide Ruff `E9,F` checks and `git diff --check` passed. Tests independently
inject failure at every uninstall and purge checkpoint, interrupt disable and enable,
reconstruct a service after process restart, verify database-password continuity, and
inspect every Compose, image, and volume command boundary.

## Remaining Work

- IL-003 adds fixed AI Agents cleanup and feature-scoped Claude package ownership.
- IL-004 orchestrates AI Agents uninstall and remote bot cleanup.
- IL-005 exposes the lifecycle services through secured owner-bound operations.
- IL-006 supplies the shared lifecycle dialog and invalidation behavior.
- IL-008 adds Mattermost lifecycle controls after the API and shared UI are available.
