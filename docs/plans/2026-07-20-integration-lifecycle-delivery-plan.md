# Integration Lifecycle Delivery Plan

Date: 2026-07-20
Status: In progress; IL-000 and IL-001 complete, but CP-021 must complete before any IL
code is deployed to Holly
Tracking prefix: `IL`
Approved design:
`docs/plans/2026-07-20-integration-lifecycle-design.md`

## Goal

Add complete, recoverable lifecycle management for the built-in Mattermost and AI
Agents integrations. Administrators must be able to disable, enable, uninstall, and,
where explicitly supported, permanently delete retained data without hidden cascading
actions or false success states.

Integration lifecycle remains on the Integrations page. Extension package lifecycle
remains under Settings > Advanced > Extensions. Built-in integration cards remain
visible after uninstall so users can set them up again.

## Product And Safety Decisions

1. Mattermost disable stops the complete managed Compose stack, including Postgres and
   alert delivery.
2. Mattermost disable is blocked until AI Agents is disabled.
3. Mattermost uninstall is blocked until AI Agents is uninstalled. LimeOS never
   cascades into agent removal.
4. Mattermost uninstall preserves declared data volumes and the database recovery
   credential. Permanent deletion is a separate purge action.
5. Mattermost purge is available only after uninstall, requires typed confirmation and
   an explicit data-loss acknowledgement, and cannot accept a path or volume name. A
   server-owned release policy defaults it off and omits it from `allowed_actions`
   until IL-010 records destructive release evidence.
6. AI Agents uninstall removes its local runtime, credentials, usage state, and
   services. It preserves the security audit log and system users and groups.
7. AI Agents uninstall attempts remote bot cleanup, but a remote failure is a warning
   after required local cleanup succeeds.
8. Claude Code removal is selected by default. Package reconciliation becomes
   feature-scoped so an uninstalled agent is outside global Claude management and a
   nightly or update-time reconcile cannot reinstall Claude Code.
9. Interrupted required cleanup produces `cleanup_required`. Startup convergence must
   not repair, reinstall, start, or otherwise alter an integration in that state.
10. All lifecycle mutations, including the currently synchronous AI Agents disable
    action, require authentication, CSRF validation, the existing `extensions.admin`
    permission, and an owner-bound streamed operation slot.
11. Existing installations derive their current state without a database or
    configuration migration. Tombstones are created only when an operation starts.
12. Permanent data deletion cannot be undone by code rollback.

## Contract Summary

### Public State

Mattermost and AI Agents status responses add server-owned lifecycle facts:

```json
{
  "state": "connected",
  "installed": true,
  "retained_data": false,
  "cleanup_required": false,
  "allowed_actions": [],
  "blocked_actions": [
    {
      "action": "disable",
      "dependency_code": "agents_must_be_disabled",
      "message": "Disable AI Agents before stopping Mattermost.",
      "required_action": "disable",
      "route": "/integrations#ai-agents"
    },
    {
      "action": "uninstall",
      "dependency_code": "agents_must_be_uninstalled",
      "message": "Uninstall AI Agents before removing Mattermost.",
      "required_action": "uninstall",
      "route": "/integrations#ai-agents"
    }
  ],
  "cleanup_operation": null,
  "warnings": []
}
```

`IL-000` freezes the exact schema, including:

- lifecycle state precedence and the distinction between `installed`,
  `retained_data`, and `cleanup_required`;
- `allowed_actions` values and ordering;
- `blocked_actions` fields: action, stable dependency code, bounded message, required
  action, and internal route;
- the bounded, secret-free `cleanup_operation` projection needed to resume or retry;
- bounded warning codes and messages;
- lifecycle tombstone schema, location, ownership, modes, atomic-write rules, and
  retention/removal rules;
- the exact owned units, files, directories, packages, images, containers, Compose
  project, logical volumes, credentials, hooks, usage state, and audit data.

The client renders only server-declared actions from a fixed client allowlist. Unknown
actions are ignored and cannot become controls. Blocked-action navigation separately
allowlists the canonical `/integrations` route and the known `ai-agents` anchor;
external, absolute, malformed, and unknown routes are never navigable.

### Mutations

```text
POST /api/integrations/agents/disable
POST /api/integrations/agents/uninstall
POST /api/integrations/mattermost/disable
POST /api/integrations/mattermost/enable
POST /api/integrations/mattermost/uninstall
POST /api/integrations/mattermost/purge
```

Mutations return `202` with the existing operation ID and SSE stream contract. The
existing synchronous agent disable route is converted to this contract; it does not
retain a second synchronous execution path. Request schemas reject unknown fields. The
client cannot provide a filesystem path, unit, package, image, container, Compose
project, or volume name.

Operation errors, SSE events, audit records, logs, and public status must use stable
bounded messages. They must never expose raw exception text that can contain a path,
credential, token, webhook, DSN, environment value, or command output.

### Recovery Credential Custody

Retained-data reinstall requires the original Mattermost database password. `IL-000`
must decide and record how the unprivileged application can move and consume a
root-owned mode-`0600` recovery credential without widening read access. The recommended
contract is helper custody: fixed helper commands atomically move the active credential
to recovery storage and restore it, while neither API responses nor unprivileged
service code reads its value. Implementation does not proceed past `IL-000` until this
root/non-root boundary is fixed and tested.

### Dependency Snapshot

Agent dependency checks use a Mattermost-independent lifecycle snapshot derived from
agent configuration, units, tombstone, and owned runtime facts. Mattermost being down,
uninstalled, or unreachable must not prevent LimeOS from determining whether AI Agents
is installed or disabled, and therefore whether a Mattermost action is allowed.

### Claude Package Ownership

`IL-003` changes `config/limeos-packages.json`, `limeos_packages.py`, and
`pihealth_helper.py` as one deployable package-boundary slice. Claude Code moves from an
unconditional host baseline to an AI Agents feature-scoped desired package:

- `remove_claude_code: true` removes the LimeOS-managed apt hold, package, source, and
  signing key, then records the uninstalled feature state. All reconcile paths exclude
  Claude until a later AI Agents setup explicitly requires it.
- `remove_claude_code: false` leaves the existing package, source, key, and hold
  untouched as user-retained state. The uninstalled feature is still excluded from
  global desired state, so reconcile neither installs, upgrades, removes, nor changes
  the retained Claude package.
- AI Agents setup re-enters feature-scoped management and performs the normal compatible
  package installation and hold workflow.

Nightly, updater, startup, and manual package reconciliation must all consume the same
server-owned feature state. No path may fall back to the unconditional package manifest.

## Sprint Plan

### Sprint 0: Contract And Baseline

Goal: fix ownership, state, recovery, and rollback contracts before destructive code is
added.

| ID | Work package | Depends on | Status | Deliverable |
| --- | --- | --- | --- | --- |
| IL-000 | Baseline, ownership, lifecycle and API contract | Approved design | Complete (`94d6ae7`) | Recorded current Mattermost/agent/package behavior; frozen public state, blocked-action, tombstone, warning, cleanup-operation, ownership, recovery-credential custody, and rollback contracts |
| IL-001 | Lifecycle state and recovery repositories | IL-000 | Complete (`4163c30`) | Atomic tombstone and retained-data repositories; Mattermost-independent agent snapshot; status precedence; capability-adapter mapping; startup convergence guard; helper sandbox/drop-in migration in `scripts/migrate_runtime_state.py`; and feature-state input for package reconciliation |

Exit gate:

- Existing installed and uninstalled fixtures produce correct state without migration.
- No lifecycle file is created before an operation starts.
- Tombstones and recovery metadata are atomic, mode-safe, bounded, and secret-free.
- Missing tombstones derive legacy state, but invalid, corrupt, or unsupported tombstones
  fail closed as `cleanup_required`; they never fall back to installed or not-installed.
- Startup skips `cleanup_required` and never repairs an interrupted uninstall.
- `integration_capability_adapters.py` and its tests map disabled, retained-data, and
  cleanup-required integration states without treating them as healthy or configured.
- Runtime migration installs the exact helper sandbox/drop-in permissions required for
  the fixed cleanup and recovery-custody paths without granting directory-wide access.
- The helper-custody decision for the Mattermost recovery credential is executable and
  covered by tests.

### Sprint 1: Backend Lifecycle Services

Goal: implement idempotent local lifecycle operations behind fixed ownership
boundaries.

| ID | Work package | Depends on | Status | Deliverable |
| --- | --- | --- | --- | --- |
| IL-002 | Mattermost lifecycle service | IL-001 | Complete | Dependency-gated disable/enable; retained-data uninstall/reinstall; fixed local-image and orphan cleanup; ownership-verified purge behind a default-off server release policy; alert/package-hook cleanup; recovery-secret rotation; tombstone recovery; and status derivation |
| IL-003 | AI Agents helper and feature-scoped Claude package ownership | IL-001 | Complete (`2206cb5`) | Boolean-only Claude removal; fixed unit/path/package/source/key allowlists; coordinated `config/limeos-packages.json`, `limeos_packages.py`, and `pihealth_helper.py` reconciliation behavior; audit and identity preservation; and idempotent step results |
| IL-004 | AI Agents lifecycle orchestration | IL-001, IL-003 | Complete (`0b18b1c`) | Mattermost-independent dependency state, remote bot cleanup, required local cleanup, bounded warning completion, usage/runtime removal, and cleanup retry |

Exit gate:

- Every required cleanup step can fail independently and a retry completes without
  repeating destructive work.
- Local failures retain `cleanup_required`; remote bot failure produces a warning only
  after required local cleanup completes.
- Agent audit data, Mattermost data, alerts, and system identities remain outside the
  agent removal boundary.
- Mattermost disable preserves all data and configuration; retained-data reinstall
  proves the original database credential is reused.
- Mattermost uninstall removes only fixed LimeOS-owned local images and uses Compose
  `--remove-orphans`, but never invokes Compose with `-v`, `--volumes`, or an equivalent
  implicit volume-removal path. Tests inspect every generated Compose argument vector
  and image identifier.
- Purge resolves only fixed logical volume names to volumes carrying the expected
  Compose ownership labels. Bind mounts, external volumes, missing labels, and unknown
  layouts fail closed with bounded manual guidance.
- The server-owned purge release policy defaults off. Purge is absent from
  `allowed_actions` until IL-010 records qualifying evidence and the policy is
  explicitly enabled.
- Feature-scoped package reconciliation excludes an uninstalled agent in both Claude
  choices. When removal is true it does not reinstall Claude; when false it leaves the
  retained package untouched and unmanaged. Setup explicitly resumes feature ownership.

### Sprint 2: API And Shared User Interface

Goal: expose the lifecycle through the existing secured operation and interface
patterns.

| ID | Work package | Depends on | Status | Deliverable |
| --- | --- | --- | --- | --- |
| IL-005 | Lifecycle APIs, authorization and operation streaming | IL-002, IL-004 | Planned | Six strict streamed mutation routes including converted agent disable, server-owned actions and dependency blocks, owner-bound SSE operations, stable public failures, redaction, and lifecycle audit events |
| IL-006 | Shared lifecycle UI foundation and invalidation | IL-000 | Planned | Existing `ActionMenu` and `ModalOverlay` reused with a shared lifecycle dialog; cross-card refresh callback/shared invalidation; strict action and route filtering; typed confirmation, acknowledgement, progress, warning completion, failure retention, retry, and focus restoration |

Exit gate:

- Anonymous, non-admin, missing-CSRF, malformed, unknown-field, wrong-confirmation,
  concurrent, and stale-state requests fail before a helper or Compose call.
- Operation history, SSE, audit, logs, and API errors contain no exception strings,
  paths, credentials, tokens, webhook URLs, DSNs, or environment values.
- The shared dialog cannot close during required cleanup, announces state changes, wraps
  bounded output, and restores focus to its trigger.
- Client action filtering accepts only known lifecycle actions and never infers an
  action from display state.
- Blocked-action navigation accepts only the canonical Integrations route and the known
  AI Agents anchor. External, malformed, absolute, and unknown server routes remain
  inert.
- The shared invalidation contract refreshes Mattermost and AI Agents together after a
  lifecycle transition, dependency failure, retry, or operation completion; IL-007 and
  IL-008 do not introduce card-local stale copies.
- Same-slice regression tests prove the shared `ActionMenu` change preserves its
  existing Containers, Stacks, and Disks consumers.

### Sprint 3: Integration Workflows

Goal: complete both integration cards without duplicating lifecycle semantics.

| ID | Work package | Depends on | Status | Deliverable |
| --- | --- | --- | --- | --- |
| IL-007 | AI Agents lifecycle UI | IL-004, IL-005, IL-006 | Planned | Streamed disable, enable/repair and uninstall; write-only Mattermost admin credentials; default-on Claude removal; remote warning result; cleanup retry; persistent not-installed card; and stable `#ai-agents` focus target |
| IL-008 | Mattermost lifecycle UI | IL-002, IL-005, IL-006 | Planned | Dependency-blocked disable/uninstall, enable, retained-data uninstall/reinstall, release-gated purge confirmation, cleanup retry, persistent card, shared invalidation, and direct focus/link to AI Agents |

Exit gate:

- Administrator and non-admin views expose only permitted actions.
- A blocked Mattermost action names AI Agents, states the required action, and moves
  keyboard and visual focus to the stable AI Agents card anchor.
- Agent uninstall requires Mattermost administrator username and password for remote bot
  cleanup. The password is write-only, is cleared immediately after operation creation
  and again on completion/cancel/close, is never logged or persisted, and must be entered
  again for retry after refresh.
- Full success, success with warning, blocked, interrupted, cleanup-required,
  retained-data, and not-installed states remain distinct after refresh.
- The purge UI remains completely unexposed until the server includes `purge` in
  `allowed_actions`; retained data alone never causes the client to infer or show it.
- Menus, confirmations, progress, and recovery remain usable without horizontal
  overflow at phone, tablet, and desktop widths.

### Sprint 4: Release Hardening And Target Signoff

Goal: prove recovery, compatibility, and target behavior before release.

| ID | Work package | Depends on | Status | Deliverable |
| --- | --- | --- | --- | --- |
| IL-009 | Cross-domain lifecycle hardening | IL-005, IL-007, IL-008 | Planned | Failure-at-every-step, security, startup, package reconciliation, accessibility, responsive, existing-workflow, full-suite, and committed-bundle release evidence |
| IL-010 | Holly canary and release signoff | IL-009, CP-021 | Planned | Recorded upgrade, dependency gates, disable/enable, agent uninstall, retained-data uninstall/reinstall, recovery, rollback, purge disposition, and GO/NO-GO evidence on `holly@192.168.0.45` |

Exit gate:

- The complete backend and Playwright suites pass without reducing CP-020 coverage.
- Mattermost alerts, package notifications, AI read-only isolation, Extensions, mounts,
  shares, and the normal updater remain operational.
- The frontend bundle is committed and source-digest checked; Holly requires no npm.
- Holly completes the non-destructive lifecycle and rollback checklist without losing
  Mattermost history, agent audit data, or unrelated provider configuration.
- Purge receives destructive target evidence on disposable data or remains unreleased.

## Parallelism And Critical Path

Local implementation may start while CP-021 is being prepared, but no IL commit is
deployed to Holly until CP-021 has recorded the capability-provider baseline.

After `IL-000`:

- `IL-001` and `IL-006` may run in parallel; `IL-006` proceeds against the frozen
  contract and fixtures while backend services are implemented.
- `IL-002` and `IL-003` may run in parallel after `IL-001`; `IL-004` starts only after
  `IL-003` completes.
- `IL-007` and `IL-008` may run in parallel after the API and shared UI foundation.

The release critical path is:

```text
                 +-> IL-001 -> IL-002 ----------+
CP-021 -> IL-000 |          +-> IL-003 -> IL-004 +-> IL-005 -+
                 +-> IL-006 ----------------------------------+-> IL-007 + IL-008
                                                                  -> IL-009 -> IL-010
```

`IL-003 -> IL-004` is part of the critical path, not optional parallel cleanup.
`IL-006` feeds both UI slices. `IL-009` and `IL-010` are serial release gates and are not
split across partially merged implementations.

## Test Strategy

Backend and helper tests cover:

- lifecycle state precedence, server-owned allowed and blocked actions, bounded warnings,
  and status reconstruction after process restart;
- atomic tombstones, ownership and modes, cleanup-operation projection, recovery-secret
  custody, corrupt/unsupported tombstone failure, and absence of secret values from
  public state;
- integration capability-adapter mapping for disabled, retained-data, and
  cleanup-required states;
- authentication, CSRF, `extensions.admin`, operation ownership, concurrency, strict
  payloads, confirmations, dependency races, redaction, and audit;
- Mattermost disable/enable, uninstall with retained data, credential-preserving
  reinstall, fixed local-image/remove-orphans cleanup, proof that `-v` and `--volumes`
  are never invoked, exact-volume purge, default-off purge release policy, and
  fail-closed unknown storage layouts;
- agent local cleanup, optional Claude removal, remote bot success and warning, audit
  retention, independent dependency snapshots, and idempotent retry;
- nightly, updater, startup, and manual package reconciliation with AI Agents installed,
  disabled, uninstalled with Claude retained, and uninstalled with Claude removed;
- startup behavior for connected, disabled, not-installed, and `cleanup_required` states;
- failure injection before and after every required cleanup step.

Frontend and Playwright tests cover:

- administrator and non-admin controls;
- strict filtering of unknown, stale, or contradictory server actions;
- blocked route filtering for external, malformed, noncanonical, and unknown anchors;
- dependency-blocked Mattermost actions and stable AI Agents anchor/focus;
- typed confirmations, irreversible acknowledgement, checkbox defaults, and stale-state
  submission failures;
- streamed success, warning, failure, refresh, cleanup retry, and retained-data reinstall;
- agent administrator-password clearing after operation creation and every terminal or
  dismissed state, with fresh entry required after refresh and no browser persistence;
- ActionMenu keyboard use, ModalOverlay focus trap/restore, live regions, and responsive
  dialogs at phone, tablet, and desktop widths;
- ActionMenu regressions across existing Containers, Stacks, and Disks consumers and
  cross-card invalidation after every integration lifecycle result;
- purge remaining hidden until the server-owned action allowlist exposes it;
- persistent cards and existing setup, alert policy, test delivery, agent permissions,
  usage, and audit workflows.

Release verification includes the full non-E2E and Playwright suites, the capability
provider security subset, production build, committed-bundle digest, interaction scan,
and `git diff --check`. Test totals must not fall below the CP-020 baseline of 1,690
non-E2E passes plus one hardware skip and 141 Playwright passes; new lifecycle cases are
additional.

## Per-Slice Commit Discipline

1. Each `IL` slice ends in an independently deployable atomic implementation commit.
2. Focused tests for that slice pass before the commit. A frontend slice includes its
   rebuilt and published `static/v2` bundle in the same implementation commit.
3. When `IL-005` converts agent disable to streaming, the same atomic slice updates the
   existing client call to consume the operation stream. No commit may leave the
   committed frontend expecting the removed synchronous response.
4. Each slice records its contract, files, tests, compatibility, deployment, rollback,
   and known limitations in `Docs/LIMEOS_INTEGRATION_LIFECYCLE_ILxxx_*.md`.
5. The tracker status and evidence document are committed immediately after the runtime
   commit, with the runtime hash recorded. The next slice starts from a clean worktree.
6. Do not combine unrelated CP, AA, storage, package, or UI refactors with an IL commit.
7. Do not squash away slice boundaries before Holly signoff; the commit range is part of
   rollback evidence.

## Holly Canary

CP-021 must complete first so the pre-lifecycle capability-provider state is attributable
and recoverable.

### Preflight

1. Record revision, worktree state, OS, architecture, service health, updater state, and
   committed frontend bundle digest.
2. Record the Mattermost Compose project, container and image IDs, exact logical and
   resolved volume names, Compose ownership labels, and mount types.
3. Record non-secret configuration hashes and credential/recovery-file ownership, mode,
   and hash without printing contents.
4. Record team and channel IDs and create a recognizable retention-test post and upload.
5. Record agent units, process groups, supplementary groups, Claude package/hold/auth
   status, and agent audit-log hash and line count.
6. Export provider configuration and verify Disks, Pools, Protection, Extensions,
   Mattermost alerts, and AI Agents against the CP-021 baseline.
7. Create and verify a restorable Mattermost data backup before any uninstall test.

### Canary Sequence

1. Update through the normal LimeOS updater. Record revision, operation output, service
   state, and bundle digest; no npm installation is permitted.
2. Verify non-admin lifecycle controls and direct mutation requests are denied.
3. With AI Agents active, verify Mattermost disable is blocked and changes no state.
4. Disable AI Agents, disable Mattermost, and confirm Mattermost, Postgres, and alertd
   stop while configuration and volumes remain.
5. Enable Mattermost and verify health, the retained post/upload, alert delivery, and
   package-update delivery. Confirm AI Agents remains disabled until explicitly enabled.
6. Verify Mattermost uninstall is still blocked while AI Agents is installed but
   disabled.
7. Record the selected Claude option, then uninstall AI Agents with fresh Mattermost
   administrator credentials. Verify owned units, runtime, credentials, and usage state
   are removed; audit and identities remain; Mattermost and alerts remain operational;
   bot cleanup success or warning is explicit; and no credential appears in operation,
   audit, service, or browser logs.
8. Run package reconciliation and restart convergence. Confirm neither repairs the
   uninstalled agent. If Claude removal was selected, confirm Claude remains absent. If
   retention was selected, confirm the exact retained package remains untouched and is
   not treated as globally managed.
9. Uninstall Mattermost with data retained. Verify owned containers, active integration
   files, alert/package hooks, and generated runtime are removed while exact declared
   volumes and the protected recovery credential remain.
10. Reinstall Mattermost. Verify the same database, post, upload, team/channel, alerts,
    and credential continuity.
11. Reinstall AI Agents. Reinstall Claude through feature-scoped setup if it was removed,
    or reuse the retained package without global reconcile changes if it was kept.
    Reauthenticate Claude, recreate/verify the bot, send a Mattermost mention, and prove
    the assistant returns a bounded read-only result.
12. Compare the agent audit log with preflight evidence. Confirm the original records
    remain and new setup/authentication/test records append without rewriting history.
13. Inject or safely simulate one interrupted required cleanup, restart the application,
    verify `cleanup_required` prevents convergence, then complete Retry cleanup.
14. Exercise all final states at desktop and phone widths, retaining screenshots,
    operation IDs, bounded logs, and browser-console results.

### Purge Evidence

Purge is not part of the routine non-destructive canary. The server release policy stays
off and the UI stays absent until a controlled IL-010 policy override is authorized. It
runs only against disposable Mattermost data on Holly or after a backup and restore
rehearsal has succeeded. Evidence must show that only expected label-owned named volumes
were removed and that the recovery credential and retained-data tombstone were cleared.
A bind mount, external volume, missing label, or unknown layout must be rejected without
deletion.

If disposable data or a verified restore window is unavailable, the purge release
policy remains off and `purge` remains absent from `allowed_actions`. Unit and mocked
Compose tests alone do not satisfy this destructive target gate. After qualifying
evidence, signoff may explicitly enable the server policy; only then may the UI expose
the server-declared purge action.

## Rollback By Lifecycle State

Rollback starts by recording the failing revision, operation ID, current tombstone,
containers, volumes, recovery-secret metadata, and service state. Do not delete runtime
files to make rollback appear clean.

| Current lifecycle state | Required rollback preparation |
| --- | --- |
| Connected or setup-required | Revert the IL commit range, redeploy the previous committed bundle, restart, and run the CP-021 baseline checks |
| Disabled | Re-enable with the IL version and verify health before code rollback |
| Mattermost uninstalled with retained data | Reinstall with the IL version, prove retained history and alerts, then roll back code |
| AI Agents uninstalled | Reinstall and reauthenticate before rollback when the previous release is expected to keep the assistant operational |
| `cleanup_required` | Do not downgrade; retry or repair cleanup with the IL version first, then restore an installed or clean not-installed state |
| Mattermost data purged | Restore the verified external backup; reverting code cannot restore deleted data |

Rollback evidence records the previous and restored revisions, bundle digests, config
hashes, volume inventory, service state, Mattermost retention marker, agent audit hash,
automated results, manual workflow results, and final decision. The same Holly checks run
against the previous revision. Provider, alert-policy, mount, share, and unrelated
integration configuration must not be recreated or deleted during rollback.

## Release Acceptance

1. Both integration cards remain discoverable after uninstall and offer valid setup or
   retained-data actions.
2. Disable, uninstall, and delete data communicate distinct effects and preservation
   boundaries.
3. Mattermost dependency gates use an independent agent lifecycle snapshot and never
   cascade into agent actions.
4. Every displayed lifecycle action is server-declared and client-allowlisted.
5. Partial required cleanup never reports success and survives application restart as
   `cleanup_required` with Retry cleanup.
6. Startup convergence never repairs an interrupted uninstall.
7. Removing Claude Code changes desired package state so automated reconciliation does
   not reinstall it.
8. Agent uninstall preserves audit data, system identities, Mattermost, alerts, and
   unrelated integrations.
9. Mattermost retained-data reinstall preserves database credentials and chat history.
10. Purge deletes only fixed, ownership-verified named volumes and fails closed for all
    other storage layouts.
11. Public errors, progress, warnings, audit events, and logs expose no raw exceptions,
    paths, credentials, tokens, webhooks, DSNs, or environment values.
12. Admin, non-admin, keyboard, focus, responsive, warning, recovery, and stale-state
    workflows pass automated coverage.
13. The committed production bundle works on Holly without npm.
14. A tested rollback returns Holly to the previous release without losing retained
    Mattermost data, agent audit data, or provider configuration.
15. Purge is released only after destructive target evidence and explicit acknowledgement
    that code rollback cannot recover deleted data.

## Deferred Work

- Cascading Mattermost removal into AI Agents removal
- Removing built-in integration cards from discovery
- Deleting agent security audit logs, system users, or groups
- General backup/export workflows beyond the release canary requirement
- Deleting bind-mounted or external Mattermost storage from the UI
- Caller-selected Compose projects, containers, images, units, packages, paths, or
  volumes
- Removing third-party extension packages from the Integrations page
- General package-feature dependency management beyond Claude Code and AI Agents
- Automatic provider switching or model invocation during lifecycle operations
