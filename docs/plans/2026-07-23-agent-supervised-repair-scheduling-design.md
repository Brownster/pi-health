# Agent Supervised Repair Scheduling Design

Date: 2026-07-23

Status: Accepted implementation detail for AO-009

Parent plan: `docs/plans/2026-07-20-agent-operations-autonomy-implementation-plan.md`

Depends on: AO-008 repair-canary signoff

## Objective

AO-009 adds health-triggered supervised repair for canaried R1 operation-target pairs.
The framework supports registered R1 repairs, but the first release exposes only
`container.restart:get_iplayer`. A code-owned health assessment must fail twice before
the scheduler may act. The existing action policy, current-release canary, maintenance
window, cooldown, disruption budget, demotion overlay, and target lease must all permit
the action.

AO-009 does not let the model choose, authorise, or execute a repair. A later release may
let the model recommend an action, but every recommendation will remain subject to the
same server-owned gates.

## Service Boundary

AO-009 adds `limeops-supervised-repair.service` under a dedicated
`limeops-supervisor` identity. The service may access:

- the read-only `limeopsd` socket;
- its supervision SQLite database;
- the action ledger and action policy;
- the root-owned deployed-release marker; and
- a narrow Mattermost delivery projection containing the alerts channel, site URL, and
  existing LimeOS bot posting credential.

The service cannot access Docker, the privileged helper, the action socket, a shell
interface, the model provider, the full credentials file, or the source checkout. It
assesses targets through `limeopsd` and creates bounded scheduled actions through the
action domain. The trusted worker and isolated actuator remain the only mutation path.
Mattermost incoming webhooks return no created post identifier, so they cannot support
durable follow-up replies. The supervisor receives a separate service-owned projection
of the already-provisioned bot credential and uses only the create-post endpoint; it
does not share the agent runtime environment file.

AO-007's `limeops-report-scheduler.service` remains unchanged and read-only. Report
schedules retain fixed zero-action budgets.

## Installation Lifecycle

The supervisor belongs to the AI Agents integration, not the base LimeOS installation:

- a base installation without AI Agents creates no supervisor identity, unit, database,
  or credential projection;
- AI Agents install provisions the supervisor with the action broker and worker;
- AI Agents update and repair migrate and refresh the supervisor;
- AI Agents disable stops the supervisor and retains schedules, incidents, demotions,
  and evidence;
- AI Agents re-enable restarts the supervisor after validating retained state; and
- AI Agents uninstall removes runtime access and follows the existing retained-data
  choice for supervision state.

Fresh installs start with no schedules or canaries. Existing agent-enabled systems gain
the service through the normal update runtime refresh. Migration or provisioning failure
leaves supervised scheduling unavailable. An updated release marker makes existing
attestations stale, so each release needs a new approval-bound canary before supervision.

Disablement also invalidates every unconsumed supervision authorisation and cancels
scheduled actions that have not started. An action already executing may finish
verification, but disablement prevents another mutation. The actuator checks the
authoritative AI Agents lifecycle state immediately before execution.

## Schedule Contract

The administrator creates a schedule with this strict shape:

```json
{
  "name": "Recover get_iplayer",
  "enabled": true,
  "operation": "container.restart",
  "params": {"name": "get_iplayer"},
  "service_priority": "normal",
  "window": {
    "cron": "0 2 * * *",
    "timezone": "Europe/London",
    "duration_minutes": 60
  },
  "delivery": {
    "channel": "mattermost-alerts",
    "mode": "threaded"
  }
}
```

Trusted code derives the target, risk, capability version, assessment operation,
health predicate, interval, failure threshold, and budgets. AO-009 fixes:

- assessment interval: 600 seconds;
- consecutive failures before incident: 2;
- actions per operation-target in a rolling 24 hours: 1;
- actions per maintenance window: 1;
- automatic retries: 0;
- concurrent supervised mutations: 1; and
- execution and verification deadline: 120 seconds.

`service_priority` accepts `critical`, `high`, `normal`, or `low` and defaults to
`normal`. Priority orders due assessments, repair claims, and escalation presentation.
It never widens authority or bypasses a safety gate.

The server advertises only current, registered, canaried R1 pairs. AO-009 initially
advertises `container.restart:get_iplayer`; it does not infer targets from container
names or hard-code household service rankings.

## Assessments and Incidents

The supervisor claims one deterministic assessment bucket per schedule every ten
minutes. A unique `{schedule_id, assessed_for}` constraint prevents duplicate work after
overlap, clock replay, or restart.

For `container.restart`, the supervisor calls the code-owned `container.status` read.
The assessment fails when Docker reports the target as stopped, exited, dead, restarting,
or explicitly unhealthy. A missing or malformed response is an infrastructure error,
not a target failure.

The first failed assessment records a pending fault. The second consecutive failure
opens one durable incident and sends one Mattermost alert. A healthy assessment resets
the counter and closes an incident that needed no action. An unknown assessment breaks
the actionable streak, so stale failures cannot authorise repair; an open incident
remains visible as infrastructure-blocked. Repeated identical results update the incident
without sending another top-level message.

Assessments continue outside maintenance windows. A confirmed fault outside a window
opens an incident and reports deferred repair, but cannot authorise mutation. The first
fresh failed assessment inside the next window may request a repair. An action may finish
verification after the window closes, but no action may start after the stored window
deadline.

Each incident records assessment transitions, window deferral, active-action deferral,
budget denial, action start, verification, escalation, demotion, and recovery. Mattermost
updates stay in one incident thread.

## Authorisation and Concurrency

Scheduled authorisation runs in one transaction. It rechecks:

1. the enabled schedule and current revision;
2. the exact registered R1 operation, normalized parameters, and target;
3. supervised policy for the scheduled trigger;
4. an eligible canary for the current release and capability version;
5. the absence of an active demotion;
6. a fresh in-window failed assessment and window deadline;
7. the rolling cooldown and per-window disruption budgets; and
8. the absence of a non-terminal action for the exact operation-target pair.

The transaction writes one supervision authorisation, one target lease, and one
scheduled action with a stable occurrence idempotency key. It charges the disruption
budget only when it creates the action.

The exact-target lease spans interactive and scheduled triggers. Actions in `proposed`,
`awaiting_approval`, `authorised`, `executing`, or `verifying` block a scheduled action.
This prevents supervision from overtaking an agent request or a pending administrator
decision.

Immediately before mutation, the actuator rechecks the authorisation, window deadline,
policy, canary, demotion, target lease, capability contract, precondition, and kill
switch. The supervisor never calls the action socket. Worker restart and scheduler
restart address the existing action and occurrence instead of creating another action.

The supervisor obtains the action precondition through the internal, non-model-advertised
`action.precondition` broker read. The privileged broker calculates an opaque hash with
the same private capability status reader used by the actuator; raw container IDs, image
IDs, and start timestamps do not enter the public `container.status` response. The
authorizer requires the returned operation, capability version, target, normalized
parameters, and hash to match its current contract before it creates an action.

## Budgets, Demotion, and Recovery

A successful supervised repair starts a rolling 24-hour cooldown. Another confirmed
fault during that period opens or updates an incident, reports `budget_blocked`, and
performs no mutation. AO-009 never retries an action automatically.

Execution failure, uncertain verification, verification failure, expired authorisation,
time-budget breach, audit failure, or identity failure creates an exact-target demotion
overlay. The action ledger stores:

```text
demotion_id
operation
target
cause
source_action_id
release_commit
demoted_at
cleared_by_type
cleared_by_id
cleared_by_username
cleared_at
recovery_action_id
revision
```

One active demotion may exist for an exact operation-target pair. The overlay changes
effective supervised authority to approval without rewriting the administrator's policy
or revoking the canary. The action service and actuator enforce it independently.

Clearing a demotion requires an approval-bound repair that succeeded with terminal code
`verified` after the demotion on the current release. An authenticated administrator
must then clear it explicitly. Time passage, a green assessment, service restart, policy
rewrite, or model request cannot clear a demotion.

Policy, ledger, audit, read-broker, release-marker, or health-contract failure blocks
mutation. The supervisor retains prior assessments for evidence, invalidates the
actionable failure streak, records a bounded infrastructure transition, and suppresses
repeated identical alerts.

## API and Interface

AO-009 adds authenticated administrator APIs for:

- supervised repair schedule list, create, detail, update, enable, and disable;
- incident list and detail;
- demotion list; and
- explicit demotion clearing.

Mutations require CSRF, `extensions.admin`, strict JSON, and the current schedule or
demotion revision. Responses use `Cache-Control: no-store`. The server rejects unknown
fields, arbitrary predicates, non-R1 capabilities, unavailable targets, stale canaries,
and unregistered priority values.

The Automation screen keeps report schedules and supervised repairs separate. Each repair
card shows operation, target, priority, window, current canary release, assessment
history, consecutive failures, incident state, last action, cooldown, disruption budget,
demotion, and effective authority. Safety limits remain read-only. Enabling supervision
and clearing demotion require two-step confirmation.

Disabled AI Agents, stale canaries, infrastructure failure, active actions, closed
windows, budget blocks, and demotions appear as distinct states. Disabling AI Agents
pauses assessments and actions while retaining the records needed for re-enable.

## Verification

Unit and concurrency tests cover:

- strict schedule validation and server-derived fields;
- priority ordering and bounded assessment concurrency;
- ten-minute buckets, consecutive failure, recovery reset, and incident suppression;
- window boundaries, daylight-saving transitions, timezone changes, and clock skew;
- rolling cooldown, per-window budget, zero retry, and global mutation limit;
- interactive and scheduled active-action exclusion;
- occurrence, action, lease, incident, and budget idempotency;
- scheduler, worker, and actuator restart recovery;
- policy, canary, release, identity, audit, and telemetry failure;
- every demotion cause and recovery requirement; and
- kill-switch enforcement at authorisation and mutation.

API and browser tests cover authentication, roles, CSRF, revisions, confirmations,
blocked states, incident history, demotion recovery, and accessible responsive controls.
Provisioning tests cover fresh AI Agents install, enabled-agent update, repair,
disable/re-enable, uninstall retention, and fail-closed migration. AO-007 tests continue
to prove that the report scheduler cannot create actions.

## Holly Canary

The target-Pi release check:

1. updates Holly and confirms the supervisor, report scheduler, worker, actuator, policy,
   ledger, and sandbox boundaries;
2. records policy, action, supervision, incident, and container baselines;
3. runs one new approval-bound `container.restart:get_iplayer` canary for the deployed
   release and attests it;
4. creates one short supervised maintenance window with `normal` priority;
5. deliberately stops `get_iplayer`;
6. observes two ten-minute failed assessments, one threaded incident, and one scheduled
   action;
7. verifies one restart, a new start time, acceptable health, one budget charge, and one
   cooldown;
8. proves a non-terminal interactive action defers supervision;
9. proves cooldown denial, schedule disablement, and restart persistence;
10. restores the original policy and schedule state while retaining audit, incident,
    action, canary, and cooldown evidence.

Deterministic integration tests inject execution and verification failures to prove
demotion and recovery without risking Holly's workload.

## Delivery Slices

1. Add supervision schedules, assessments, incidents, budgets, and adversarial storage
   tests.
2. Add exact-target action leases, authorisations, demotion overlays, and actuator
   enforcement.
3. Add the dedicated supervisor runtime, Mattermost incident delivery, and restart
   recovery.
4. Add authenticated APIs and the Automation interface.
5. Add AI Agents lifecycle provisioning, update migration, and sandbox tests.
6. Run the complete suite and Holly canary, record evidence, and close AO-009.
