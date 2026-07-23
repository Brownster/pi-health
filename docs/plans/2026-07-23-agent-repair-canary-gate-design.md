# Agent Repair Canary Gate Design

Date: 2026-07-23

Status: Accepted and target-Pi signed off 2026-07-23

Parent plan: `docs/plans/2026-07-20-agent-operations-autonomy-implementation-plan.md`

## Objective

AO-008 creates the evidence gate between approval-bound interactive repairs and
supervised scheduling. An administrator may attest one verified interactive repair.
That attestation permits only the exact `{operation, target, scheduled trigger,
capability version}` tuple to use supervised authority. It grants no autonomous
authority and does not schedule an action.

AO-009 will consume this gate when it adds repair schedules, cooldowns, disruption
budgets, automatic demotion, and escalation. Until then, the action kill switch remains
engaged and scheduled action budgets remain zero.

The first target-Pi canary is `container.restart` for `get_iplayer` on Holly.

## Trust Boundary

The source action must already exist in the server-owned action ledger. A client supplies
only its action ID. Trusted code derives the operation, target, trigger, risk,
capability version, authority mode, state, and verification evidence.

An eligible source action must:

- be `R1`;
- use the `interactive` trigger and `approval` authority;
- finish in `succeeded`;
- contain a recorded successful verification event;
- match the current code-owned capability contract and version; and
- have no existing canary attestation.

Only an authenticated local administrator with `extensions.admin` may attest or revoke
canary evidence. Mattermost actors, the model provider, the report scheduler, the action
worker, and the actuator cannot mutate attestations.

## Durable Attestations

The existing action SQLite database gains a `canary_attestations` table:

```text
attestation_id
operation
target
trigger
capability_version
risk
source_action_id
release_commit
attested_by_type
attested_by_id
attested_by_username
attested_at
revoked_by_type
revoked_by_id
revoked_by_username
revoked_at
```

`source_action_id` references the immutable action record and is unique. A partial unique
index allows at most one active attestation for an exact operation, target, trigger, and
capability version. Revocation retains the original evidence and permits a later canary
to create a new active attestation.

Attestation and revocation append bounded `canary_attested` and `canary_revoked` events
to the source action. An audit write failure aborts the state change. No request field
can override derived evidence or attribution.

## Canary Gate

Policy validation asks a `CanaryGate` whether a proposed authority tuple is eligible.
The gate returns success only when:

1. the requested mode is `supervised`;
2. the trigger is `scheduled`;
3. the capability risk is `R1`;
4. the capability declares supervised authority as eligible; and
5. an active attestation matches the exact operation, target, trigger, and capability
   version.

`autonomous` remains unavailable. Supervised interactive and event authority remains
unavailable. R2 and R3 operations remain approval-bound. Observe, propose, and approval
behaviour does not change.

The application validates policy before requesting a write. The privileged helper
repeats the same validation against the installed registry and action database before it
writes the policy file. A missing or unreadable database, unknown operation, stale
capability version, revoked attestation, or audit failure denies the change.

Changing a capability version makes earlier evidence ineligible without deleting it.
The global kill switch continues to block supervised authorisation and execution even
when a valid attestation exists.

## API

AO-008 adds:

```text
GET  /api/integrations/agents/canaries
POST /api/integrations/agents/actions/<action_id>/canary
POST /api/integrations/agents/canaries/<attestation_id>/revoke
```

All routes require authentication and `extensions.admin`. Mutations require CSRF.
Responses use `Cache-Control: no-store`.

The create route accepts an empty JSON object. The server uses the current local session
actor and source action. Repeated creation for the same source action returns the
existing attestation without changing attribution or creating a second audit event.

The revoke route also accepts an empty JSON object. Revoking an active attestation is a
single transition. Repeated or concurrent revocation returns a bounded conflict.

List responses contain active and revoked attestations plus the current gate status.
They expose no raw executor output, private errors, secrets, or unrestricted evidence.

## Failure Handling

The gate fails closed under:

- missing, corrupt, insecure, or unavailable action storage;
- a missing or non-terminal source action;
- execution or verification failure;
- wrong risk, trigger, authority mode, target, or capability version;
- forged, renamed, removed, or non-local administrator identity;
- duplicate or concurrent attestation and revocation;
- capability removal or contract-version change;
- policy reload during gate-state change;
- kill-switch activation before authorisation or execution; and
- failure to persist the action event or audit record.

Public errors use fixed codes and messages. Host data and exception text stay out of API
responses and the ledger.

## Adversarial Verification

Unit and contract tests cover:

- forged source records and client-supplied evidence fields;
- R2, proposed, rejected, failed, rolled-back, and unverified actions;
- operation, target, trigger, risk, and capability-version mismatch;
- duplicate and concurrent attestation;
- duplicate and concurrent revocation;
- stale and revoked evidence;
- actor impersonation and Mattermost-originated mutation;
- autonomous mode and supervised interactive or event mode;
- unrelated operation-target pairs;
- database, action-event, audit, and registry failure;
- policy reload after revocation;
- kill-switch enforcement; and
- symlink, traversal, shell metacharacter, Unicode confusable, and oversized input.

Existing action, actuator, API, Mattermost callback, browser, and report-scheduler suites
remain release gates.

## Holly Canary

The target-Pi release check:

1. records the deployed release, action policy, action ledger count, `get_iplayer`
   container identity, start time, health, and dependencies;
2. backs up the action policy;
3. enables only interactive approval for `container.restart:get_iplayer`, names one
   local administrator as approver, and briefly releases the kill switch;
4. creates and approves one exact restart proposal;
5. verifies a new container start time, running state, acceptable health, one execution,
   and complete audit correlation;
6. attests that successful source action;
7. proves scheduled supervised policy validates for
   `container.restart:get_iplayer` but fails for an unrelated target;
8. restarts the dashboard, action broker, and worker, then confirms the attestation,
   source action, and execution count remain singular;
9. restores the backed-up approval policy and engages the kill switch; and
10. retains the active attestation as evidence while the restored baseline keeps every
    operation and scheduled target disabled until AO-009.

Any unexpected container state, duplicate action, missing event, failed verification,
or policy-restore failure stops the canary and leaves supervised scheduling locked.

### Target-Pi Signoff

Holly passed the release check on 2026-07-23 at merge commit
`37cddac1d7839deb68e61140620e775863406832`:

- The deployed checkout and root-owned release marker matched the merge commit.
  `pi-health.service`, `limeops-actuatord.service`, and
  `limeops-action-worker.service` were active.
- The baseline ledger contained no actions, events, or attestations. The root-owned
  action policy had SHA-256
  `afce77a417daffe6b6910ac9dfd14031b8fdbdec49a6c612b77389bc339444d8`,
  its kill switch engaged, and every operation disabled.
- The temporary policy enabled only interactive approval for
  `container.restart:get_iplayer` by `local:holly`. Action
  `0d63228954a5466a9edbab5dbf9b852b` completed as `succeeded` with terminal code
  `verified`.
- `get_iplayer` retained its container and image identities, remained running without
  an unhealthy state, and moved from start time
  `2026-07-19T02:06:35.264753154Z` to
  `2026-07-23T18:43:57.528159094Z`.
- The single execution-start and success events shared action audit ID
  `41c774394a4d42d3a5287865e5d7eab0`.
- Attestation `4298e005-912f-46dd-8253-6bbbb7eda63d` was recorded against the source
  action, capability version 1, risk R1, the scheduled trigger, and the deployed release.
  Its status remained `eligible`; autonomous authority remained unavailable.
- Both application validation and the independent root helper accepted supervised
  scheduling for the exact attested target. Both rejected supervised scheduling for an
  unrelated target.
- Restarting the dashboard, actuator, and worker retained exactly one action, one
  execution-start, one success, one canary event, and one active attestation.
- The original policy was restored byte-for-byte, the kill switch was engaged, no
  operation or target remained enabled, and the temporary rollback copy was removed.
  The active attestation remains durable evidence for AO-009.

## Delivery Slices

1. Add the attestation store, domain service, and adversarial storage tests.
2. Add authenticated APIs and stable bounded errors.
3. Enforce the gate in application and helper policy validation.
4. Surface gate status in the Automation policy view.
5. Run the complete suite and Holly canary, record evidence, and close AO-008.
