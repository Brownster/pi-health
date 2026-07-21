# Agent Operations and Autonomy Implementation Plan

Date: 2026-07-20

Status: Implementation underway; write-disabled foundation landed 2026-07-21

Precondition: AA-009 read-only target signoff

Supersedes the delivery detail in: `Docs/LIMEOS_ASSISTANT_CAPABILITY_ROADMAP.md`

## Implementation Status

The first deployable slice now includes immutable Mattermost actor IDs, code-owned
capability contracts, deny-by-default action policy, a transactional action ledger,
expiring single-use approvals, a separate actuator socket and identities, verified
`container.start` and `container.restart`, authenticated action APIs, and private local
finding drafts. Shipped defaults keep the kill switch on and both repair operations
disabled.

AO-005 now has capability, policy, cancellation, approval, rejection, detail, history,
and listing APIs. The AI Agents browser card now provides action review and approval,
private finding review and editing, and an administrator policy editor for exact target
allowlists, approvers, proposal expiry, authority modes, and the kill switch. Mattermost
approval controls remain outstanding. AO-006 currently covers only container start and
restart. Scheduling, installation, configuration, optimisation, GitHub publication, and
agent-authored pull requests remain later work packages.

## Goal

Extend the provider-neutral LimeOS assistant from read-only investigation into a
controlled operations agent that can repair, maintain, install, configure, review, and
optimise LimeOS. Begin with approval-bound changes, then reduce approvals for individual
allowlisted operations and targets after evidence shows they are safe and effective.

The same system must turn defects and capability gaps into private, redacted bug or
feature-request drafts. A human reviews every external submission. Agent-authored code
and pull requests remain a later phase.

## Accepted Product Decisions

1. Keep typed `limeops` contracts as the only model-facing operations surface. Add
   proposal-only operations, never write executors. Never grant the model shell, Docker,
   helper-socket, raw API, or arbitrary filesystem access.
2. Introduce authority by capability and target, not by provider or agent identity.
3. Use five authority modes: observe, propose, approval, supervised, and autonomous.
4. Promote authority through explicit administrator decisions backed by execution
   evidence. Never promote an operation because the model claims confidence.
5. Implement repair and maintenance before installation and configuration.
6. Add scheduled and event-driven work gradually: report-only first, then allowlisted
   action under the same policy used for interactive requests.
7. Draft bugs and feature requests locally. Require approval immediately before GitHub
   publication.
8. Defer agent-authored patches, branches, commits, and pull requests until a separate
   self-improving-code design and security review.

## Current Baseline

AA-001 through AA-009 provide a signed-off read-only path:

```text
Mattermost -> agent gateway -> read-only limeopsd -> LimeOS readers
```

Useful foundations already exist:

- `agent_gateway/gateway.py` enforces a provider-neutral typed tool loop.
- `limeops/broker.py` validates requests, checks policy, bounds execution, and writes
  fail-closed audit events.
- `limeops/operations.py` exposes bounded diagnostic operations.
- `container_operations_service.py`, `stack_operations_service.py`,
  `stack_mutation_service.py`, `catalog_service.py`, and
  `capability_lifecycle_service.py` contain trusted domain mutations that can be adapted
  instead of reimplemented.
- The held-package flow in `pihealth_helper.py` proves a narrow payload-bound approval,
  but its persistent approval is not expiring, single-use, or general enough for agent
  actions. Migrate its intent into the new broker; do not generalise its current file
  format.
- Mattermost event deduplication, conversation persistence, usage records, and a global
  disable switch are already deployed.

The current gateway sends the Mattermost username as the actor ID. Writes require the
immutable Mattermost user ID, so actor identity must be corrected before any mutation.

## Non-Goals

- Arbitrary shell commands, file reads, or file writes
- Direct Docker, systemd, helper, package-manager, or GitHub CLI access from the model
- General Compose or environment-file editing from model-produced text
- Storage topology changes, disk formatting, partitioning, mount mutation, or SnapRAID
  write and repair operations
- Credential, firewall, account, permission, or remote-access changes
- Automatic GitHub publication
- Agent-authored code changes or pull requests
- Model-selected expansion of its own permissions, targets, schedules, or budgets

## Trust Architecture

Separate proposal creation from write execution. The provider process and agent gateway
remain unprivileged even after actions ship.

```text
Mattermost mention ---------> agent gateway ---------> limeopsd (reads/proposals)
                                                         |
                                                         | typed proposal only
                                                         v
                          action orchestrator <--------- web/Mattermost approval
                                  |
                                  | authorised action ID
                                  v
                         limeops-actuatord ---------> trusted domain service/helper
                                  |
                                  v
                       verify -> rollback/escalate -> report

alert/schedule -----------> action orchestrator (same policy and action lifecycle)

evidence ledger ----------> findings service -> private draft -> approval -> GitHub API
```

Run the actuator as a second broker instance with a separate policy, socket, Unix group,
service identity, operation registry, and audit path. Suggested boundaries are:

| Boundary | Suggested path or identity |
| --- | --- |
| Read policy | `/etc/limeos/agent-policy.json` |
| Action policy | `/etc/limeos/agent-action-policy.json` |
| Read socket | `/run/limeos/limeops.sock` |
| Action socket | `/run/limeos-actions/actions.sock` |
| Read client group | `limeops-client` |
| Action worker group | `limeops-action` |
| Action state | `/var/lib/limeos/agent-actions/actions.sqlite3` |
| Action audit | `/var/log/limeos/agent-action-audit.jsonl` |
| GitHub settings | `/etc/limeos/integrations/github.json` |
| GitHub credential | `/etc/limeos/integrations/github.env` |

The `lime-agent` identity must not join `limeops-action`. It may submit only bounded
`action.propose` and `finding.propose` requests through the ordinary broker. Only the
trusted action worker may call the action socket. The action broker revalidates
operation, target, normalized payload hash, authority mode, approval, preconditions, and
expiry at execution time.

## Capability Contract

Each action is registered in code and described by a strict contract. Do not load
executable handlers, commands, or templates from configuration.

```text
operation ID
schema version
strict parameter schema and normalizer
resource/target selector
risk class
eligible authority modes
precondition reader
impact renderer
executor adapter
verification reader and success predicate
rollback adapter or explicit no-rollback reason
timeout and output limit
cooldown, rate, and disruption budget
redaction profile
audit field allowlist
```

The model submits an operation ID, parameters, evidence references, and a short reason
through `action.propose`. Trusted code normalizes the payload and renders the user-visible
proposal. Model text never defines the impact, verification, rollback, or command.

### Risk Classes

| Class | Meaning | Maximum initial authority |
| --- | --- | --- |
| R0 | Read, review, dry-run, or local draft | Observe automatically |
| R1 | Reversible, bounded, low-disruption repair | Supervised after canary evidence |
| R2 | Installation, update, or configuration mutation | Approval; supervised only after a separate target signoff |
| R3 | Destructive, sensitive, or external publication | Approval always |
| R4 | Prohibited general authority | Denied with no approval override |

GitHub issue publication is R3. Storage mutation, arbitrary execution, permission
changes, and self-modification are R4 in this plan.

## Authority Maturity

Policy applies to the tuple `{operation, target, trigger}`. For example, an interactive
restart of Jellyfin can mature independently from a scheduled restart of Mattermost.

| Mode | Behaviour |
| --- | --- |
| Observe | Diagnose and report; create no action proposal unless asked |
| Propose | Create an exact, expiring proposal but never execute it |
| Approval | Execute once after an eligible human approves the unchanged payload |
| Supervised | Execute inside a maintenance window and report every result immediately |
| Autonomous | Execute within configured budgets and report a digest unless escalation is required |

Promotion requires an administrator, a minimum sample count, an acceptable verified
success rate, no unresolved safety failure, tested rollback where applicable, and an
explicit target allowlist. The UI may recommend promotion but cannot perform it
implicitly.

Demote automatically to approval when any of these occurs:

- verification fails or remains uncertain;
- rollback fails or cannot establish the prior state;
- the capability contract or executor version changes;
- the target identity, configuration generation, or dependency set changes materially;
- the action exceeds its disruption, retry, or time budget;
- an administrator rejects or reverses a recent automated action;
- audit persistence, policy loading, or identity validation becomes unavailable.

R3 operations never progress beyond approval. R4 operations never progress beyond deny.

## Action Lifecycle

Persist action state transactionally in SQLite. Use unique constraints for proposal
idempotency keys, approval use, scheduler occurrence IDs, Mattermost event IDs, and
external publication fingerprints.

```text
diagnosed
  -> proposed
  -> awaiting_approval | authorised
  -> executing
  -> verifying
  -> succeeded
       or verification_failed -> rolling_back -> rolled_back
       or execution_failed
       or rollback_failed -> escalation_required
```

Terminal alternatives are `rejected`, `expired`, `cancelled`, `superseded`, and
`precondition_changed`. A proposal cannot return to an executable state.

Before execution, compare a capability-defined precondition fingerprint with the value
captured at proposal time. Invalidate the proposal if state changed. An approval binds
to the normalized payload hash, actor ID, operation, target, expiry, and proposal ID. It
is single-use and never exposed to the provider prompt.

Every action records:

- source trigger and correlation IDs;
- stable actor ID and display name;
- operation, target, risk class, and contract version;
- redacted before and after summaries;
- proposal, approval, policy, and maturity decisions;
- execution, verification, rollback, duration, and outcome;
- linked read-broker and action-broker audit IDs;
- operator rejection, reversal, and promotion feedback.

Store no secrets, raw environment values, access tokens, or unrestricted logs in the
ledger.

## Phase 1: Repair and Maintenance

Begin with operations that reuse existing services and have clear verification.

| Operation | Class | Initial targets | Execute through | Verification |
| --- | --- | --- | --- | --- |
| `container.start` | R1 | Explicit container allowlist | `ContainerOperationsService.control` | Container reaches expected running/healthy state |
| `container.restart` | R1 | Explicit container allowlist | `ContainerOperationsService.control` | New start time and expected health |
| `stack.reconcile` | R1/R2 | Explicit stack allowlist | `StackOperationsService.run(..., "up")` | Expected services running; no new unhealthy service |
| `extension.repair` | R2 | Installed extension allowlist | `ExtensionLifecycleService.transition` | Registry, import, and provider health pass |
| `integration.repair` | R2 | AI Agents first; Mattermost later | Integration service repair method | Integration-specific connected/healthy state |
| `packages.reconcile` | R2 | Shipped package manifest only | Typed helper package reconcile | Manifest compliance and required units healthy |
| `job.retry` | R1/R2 | Named failed job types only | Owning service method | Job-specific success and no duplicate effect |

Do not include container stop, image update, stack down, package names supplied by the
model, arbitrary service restart, or generic cleanup in the first repair set.

Interactive repair ships first in approval mode. Scheduled maintenance initially runs
the read-side diagnostics and posts a report. After the repair canary gate, only R1
operations may enter supervised mode. R2 remains approval-bound until Phase 2 signoff.

Each operation needs a domain runbook that defines expected healthy state, maximum
downtime, dependencies, retry count, cooldown, rollback or recovery, and escalation
message. A restart that leaves a dependency unhealthy is a failed repair even if the
underlying API call returned success.

## Phase 2: Installation and Configuration

Installation and configuration use schema-derived payloads and trusted mutation
services. The agent may gather requirements conversationally, but the server generates
the final form, redacted diff, impact, and validation result.

### Installation Operations

| Operation | Class | Boundary |
| --- | --- | --- |
| `catalog.install` | R2 | Catalog ID, declared fields, dependencies, and target stack only |
| `extension.install` | R2 | Configured source and package allowlists only |
| `extension.update` | R2 | Installed extension, pinned source, compatible version only |
| `integration.install` | R2 | Built-in integration adapters only |

Reuse `CatalogService.install` and `ExtensionLifecycleService`. Preserve their existing
locks, validation, dependency checks, and operation progress. Installation proposals
must show new services, ports, mounts, images, dependencies, required secrets, estimated
downtime, and rollback limitations without displaying secret values.

### Configuration Operations

Start with domains that already have typed configuration services:

- AI Agent limits, channels, schedules, and action allowlists;
- backup and update schedules;
- capability-provider setup and repair fields;
- catalog-managed service fields;
- validated stack service patches that can be expressed structurally.

Every configuration action must provide validate, preview, apply, verify, and restore.
Use a generation number or content hash for optimistic concurrency. Create the backup
before applying, write atomically, and retain the backup until the observation window
closes. Redacted previews show keys and safe values; secret fields show only set, replace,
or clear.

Do not pass model-produced Compose YAML or `.env` text to
`StackMutationService.save_compose` or `save_env`. Add a structured patch compiler with
an allowlisted schema, then render and validate the full document inside trusted code.

## Phase 3: Review and Optimisation

Add reviews before optimisation actions. Reviews correlate existing bounded evidence:

- health and restart history;
- CPU, memory, disk, and network trends;
- package and configuration drift;
- backup, alert, and scheduled-job outcomes;
- repeated incidents, repairs, rollbacks, and operator feedback;
- unused or consistently constrained services.

An optimisation proposal contains a baseline, hypothesis, exact change, success metric,
observation window, stop condition, and rollback threshold. Examples include adjusting a
bounded resource limit, schedule, retention value, or worker count through an existing
configuration schema.

Do not treat lower resource use as success by itself. Verification must also preserve
service health, latency/error thresholds where available, backup completion, and the
absence of new alerts. Speculative recommendations remain in propose or approval mode.
Optimisation cannot become supervised until the system has recorded both a successful
change and a successful rollback rehearsal for that capability type.

## Scheduled and Event-Driven Work

Use one scheduler and orchestrator for interactive, scheduled, and alert-triggered work.
Schedules define:

- stable schedule ID and owner;
- read checks and optional action capability;
- target allowlist and authority mode;
- maintenance window and timezone;
- maximum actions, downtime, retries, and model invocations per window;
- cooldown and incident suppression rules;
- notification channel and digest policy.

The first scheduler release is report-only. Supervised scheduling ships only after the
interactive operation passes its target-Pi canary. Never let a schedule alter its own
definition, widen its targets, promote authority, or suppress failed-action alerts.

Alert-triggered repair must require consecutive failure evidence and a current incident.
Recovery closes the incident; it does not erase the action record. A global kill switch
must stop new scheduled and autonomous execution without disabling read-only diagnosis or
alert delivery.

## Findings and GitHub Reporting

### Local Drafts

Create a findings service independent of the provider conversation store. A finding is
one of `bug`, `feature_request`, `maintenance_gap`, or `documentation_gap` and contains:

- title and concise redacted summary;
- affected LimeOS and component versions;
- expected and actual behaviour for bugs;
- bounded reproduction steps and evidence references;
- impact and frequency;
- workaround, if known;
- confidence and the facts supporting it;
- suggested acceptance criteria;
- source type: user discussion, failed action, recurring incident, review, or manual;
- privacy/redaction result and duplicate fingerprint.

Do not copy private chat or logs verbatim. Summarise the necessary facts and let the user
edit or delete the draft. Draft creation is local and may happen automatically when the
feature is enabled. Publication always requires a rendered preview and a fresh approval.

### Deduplication

Normalize component, error class, affected version range, and reproduction signature
into a stable local fingerprint. Check open local drafts first, then search issues in the
configured repository. Suggest adding evidence to an existing issue instead of creating
a duplicate. A model similarity score may rank candidates but cannot decide publication.

### GitHub Integration

Prefer a repository-scoped GitHub App installation. Grant repository metadata read and
Issues read/write only for selected repositories. Do not grant Contents, Pull requests,
Workflows, Administration, or organization permissions in this phase. A fine-grained
personal access token with repository-scoped Issues write is an operator fallback.

Store the installation credential outside agent-readable paths. Trusted integration code
calls the versioned GitHub REST API; the model never receives a token or arbitrary URL
client. The publisher accepts only a configured repository ID, title, body, and
allowlisted labels. It cannot set assignees, milestones, projects, or arbitrary issue
fields initially.

Publication is an R3 action with its own idempotency key. Handle GitHub validation,
permission, disabled-issues, service-unavailable, and secondary-rate-limit failures as
retryable or terminal states without creating a second issue. Record the returned issue
ID and URL, but never the credential or full remote response.

## API and Interface Plan

Keep policy calculation server-owned. Suggested authenticated, CSRF-protected endpoints:

```text
GET  /api/integrations/agents/actions/capabilities
GET  /api/integrations/agents/actions
GET  /api/integrations/agents/actions/<id>
POST /api/integrations/agents/actions/<id>/approve
POST /api/integrations/agents/actions/<id>/reject
POST /api/integrations/agents/actions/<id>/cancel

GET  /api/integrations/agents/automation/policy
PUT  /api/integrations/agents/automation/policy
GET  /api/integrations/agents/automation/schedules
POST /api/integrations/agents/automation/schedules
PUT  /api/integrations/agents/automation/schedules/<id>

GET  /api/integrations/agents/findings
GET  /api/integrations/agents/findings/<id>
PUT  /api/integrations/agents/findings/<id>
POST /api/integrations/agents/findings/<id>/approve-publication
POST /api/integrations/agents/findings/<id>/reject
```

Return allowed actions, expiry, current precondition state, risk, maturity, verification,
and rollback availability. Never make the frontend infer eligibility.

The AI Agents interface gains:

- **Actions:** proposals, approvals, progress, verification, rollback, and history;
- **Automation:** per-operation/target maturity, schedules, windows, budgets, and kill
  switch;
- **Findings:** editable drafts, duplicate candidates, redaction status, publication
  preview, and linked issues;
- **Evidence:** success rate, failures, rollbacks, rejections, and promotion readiness.

Mattermost proposals show the exact operation, target, reason, impact, expiry,
verification, rollback, and Approve/Reject controls. The listener must authenticate the
immutable Mattermost actor ID from the event or callback; usernames are display data
only. The agent posts progress and the final verified result in the originating thread.

## Work Packages

| ID | Package | Depends on | Deliverable |
| --- | --- | --- | --- |
| AO-000 | Re-baseline and threat model | AA-009 | Current service inventory, write threat model, stable Mattermost actor-ID contract, and accepted operation/risk catalogue |
| AO-001 | Capability and policy contracts | AO-000 | Strict action capability schema, separate action policy parser, contract versions, resource allowlists, and deny-by-default defaults |
| AO-002 | Action ledger and orchestrator | AO-001 | Transactional lifecycle, idempotency, preconditions, execution leases, verification, rollback, recovery, and evidence joins |
| AO-003 | Approval broker | AO-002 | Expiring actor/payload-bound single-use approval, eligible-approver policy, rejection/cancellation, and package-approval migration path |
| AO-004 | Actuator boundary | AO-001..AO-003 | Separate socket/service/group, action broker registry, action audit, hardened systemd unit, and agent isolation proof |
| AO-005 | Approval UX and APIs | AO-002..AO-004 | Server-owned allowed actions, web flows, Mattermost controls, progress, result reporting, and kill switch |
| AO-006 | Repair adapters | AO-004, AO-005 | Container start/restart, stack reconcile, extension/integration repair, package reconcile, job retry, and operation runbooks |
| AO-007 | Report-only scheduler | AO-002 | Maintenance windows, budgets, occurrence deduplication, report delivery, restart recovery, and no-write default |
| AO-008 | Phase 1 security and canary gate | AO-006, AO-007 | Adversarial suite plus interactive target-Pi repair evidence; authorises selected R1 supervised scheduling only |
| AO-009 | Supervised repair scheduling | AO-008 | Per-target R1 supervised mode, cooldowns, disruption budgets, automatic demotion, and escalation |
| AO-010 | Install/config preview foundation | AO-002..AO-005 | Schema-derived forms, redacted diffs, generation checks, backups, verify/restore contracts, and secret-field handling |
| AO-011 | Installation adapters | AO-010 | Catalog, extension, update, and built-in integration installation through existing services |
| AO-012 | Configuration adapters | AO-010 | Agent, backup, update, provider, catalog-service, and structured stack configuration operations |
| AO-013 | Phase 2 security and canary gate | AO-011, AO-012 | Install/config rollback, secret, conflict, and target-Pi evidence; R2 remains approval by default |
| AO-014 | Review and optimisation | AO-002, metric history | Evidence correlation, recurring-gap reports, experiment proposals, observation windows, and rollback thresholds |
| AO-015 | Findings and local drafts | AO-002 | Finding schema, redaction, local deduplication, editable drafts, evidence links, and privacy controls |
| AO-016 | GitHub issue integration | AO-003, AO-015 | Repository allowlist, least-privileged credential setup, remote duplicate search, approved publisher, rate handling, and linked issue state |
| AO-017 | Autonomy readiness and release gate | AO-009, AO-013, AO-014, AO-016 | Promotion recommendations, manual promotion controls, automatic demotion, full target-Pi canary, rollback, and operator guide |

### Parallel Delivery

After AO-002 lands:

- AO-003 and AO-007 can proceed in parallel.
- AO-015 can proceed without write execution and can ship as local drafts before GitHub
  credentials exist.
- AO-010 can develop against mocked approval and actuator contracts while Phase 1 repair
  is being canaried.
- AO-014 can begin with read-only reviews; optimisation mutations wait for AO-013.

Do not parallelise multiple work packages that change the action state machine, approval
binding, or actuator protocol. Freeze those contracts through AO-004 first.

## Work-Package Acceptance Details

### AO-000 to AO-005: Foundation Gate

The foundation is complete when:

1. Mattermost supplies immutable actor and channel IDs through the listener, gateway,
   proposal, approval, and audit records.
2. The agent identity cannot connect to the actuator socket or read its policy, state,
   or credentials.
3. A model can create only typed proposals; no provider tool call can execute a write.
4. Unknown fields, stale contract versions, target aliases, path traversal, and changed
   preconditions fail before handler execution.
5. Approval expires, cannot be replayed, fails for the wrong actor, and becomes invalid
   when any normalized payload field changes.
6. A crash at each lifecycle transition resumes safely without duplicate execution.
7. Audit failure blocks action execution.
8. The kill switch blocks action authorisation and execution while reads and alerts stay
   available.

### AO-006 to AO-009: Repair Gate

The repair release is complete when:

1. Each operation calls an existing trusted service through a narrow adapter.
2. Success requires a domain health check, not only a successful command return.
3. Repeated Mattermost events, approvals, scheduler ticks, and worker restarts execute
   the action at most once.
4. Failed and uncertain verification produce escalation and automatic demotion.
5. A target-Pi canary proves restart, repair, package reconciliation, failure recovery,
   cooldown, budgets, and disable behaviour.
6. Only canaried R1 operation-target pairs can enter supervised scheduling.

### AO-010 to AO-013: Install and Configuration Gate

The second release is complete when:

1. Every payload is schema-valid and generated from registered fields.
2. Preview and apply use the same normalized payload and generation fingerprint.
3. Secret values never appear in previews, audit, evidence, prompts, or progress.
4. Backup creation, atomic apply, verification, and restore are tested for every domain.
5. Dependency failures and partial installations produce a bounded recovery path.
6. No model-produced raw Compose or environment text reaches a write service.

### AO-015 and AO-016: Reporting Gate

The reporting release is complete when:

1. Drafts contain reproducible, useful information without private conversation or
   secret content.
2. Local and remote duplicate candidates appear before approval.
3. The user can edit, reject, or delete a draft.
4. Publication requires a current rendered preview and one single-use approval.
5. Only configured repositories and labels are accepted.
6. The GitHub credential cannot write contents, branches, pull requests, workflows, or
   repository settings.
7. Retries and rate-limit recovery cannot create duplicate issues.

## Security and Failure Testing

Add focused suites for:

- prompt injection in chat, logs, catalog metadata, issue text, and provider output;
- actor impersonation, renamed users, wrong-channel callbacks, and removed approvers;
- approval expiry, payload tampering, replay, double-click, and concurrent approval;
- policy reload, contract upgrade, capability removal, and stale proposals;
- worker death before execution, during execution, after side effect, during verification,
  and during rollback;
- duplicate transport events, scheduler ticks, reconnects, and GitHub responses;
- output, evidence, audit, database, and queue size limits;
- secret-pattern and privacy redaction for all proposal and finding fields;
- symlink, traversal, shell metacharacter, Unicode confusable, and target-alias inputs;
- maintenance-window boundaries, timezone changes, clock skew, cooldown, and disruption
  budgets;
- GitHub permission denial, validation error, issues disabled, network failure, and
  secondary rate limiting;
- automatic demotion and kill-switch behaviour under every failure class.

Run unit and contract suites without privileged services. Add real-socket integration
tests for both brokers, browser tests for approval and findings flows, Mattermost callback
tests, and destructive fault injection only on disposable fixtures. The final gate runs
on Holly with a recorded preflight inventory, backups, canary targets, and rollback
evidence.

## Rollout

1. Deploy AO-000 through AO-005 with every write capability disabled.
2. Enable one Phase 1 operation for one non-critical canary target in approval mode.
3. Expand approval mode target by target after verified results.
4. Enable the scheduler in report-only mode.
5. Promote canaried R1 pairs to supervised mode after AO-008.
6. Ship installation and configuration in approval mode after AO-013.
7. Ship local findings before configuring GitHub publication.
8. Enable GitHub publication for this repository only, always approval-bound.
9. Introduce optimisation experiments in propose mode.
10. Review evidence periodically and promote or demote operation-target pairs explicitly.

Rollback disables the action worker and schedules first, leaving read-only investigation
and alerts online. Preserve the action ledger, audit, findings, and backups. Remove action
socket access before removing code. Restore configuration only from a verified backup
linked to the action record.

## Release Success Criteria

1. An authorised user can ask the assistant to diagnose and repair an allowlisted target
   without granting the model general host authority.
2. Every change has an exact proposal, authorisation decision, before/after evidence,
   verification result, and audit correlation.
3. Scheduled maintenance begins read-only and can automate only explicitly promoted
   operation-target pairs within configured budgets.
4. An administrator can install supported items and adjust supported configuration
   through schema-validated, backed-up, reversible actions.
5. Failed verification stops the workflow, rolls back where defined, escalates clearly,
   and demotes autonomous authority.
6. The assistant can review recurring problems and propose measurable optimisation
   experiments.
7. The system can create a useful private bug or feature-request draft from a discussion
   or operational gap without exposing secrets or private text.
8. GitHub receives nothing until a human approves the final preview.
9. The GitHub integration cannot create code, branches, pull requests, or workflow
   changes.
10. Disabling mutations leaves read-only diagnosis, Mattermost alerts, and existing
    integrations operational.

## Deferred Follow-Up: Self-Improving Code

A later design may add repository review, patch generation, isolated test execution,
commits, and draft pull requests. It must introduce a separate source-workspace sandbox,
repository/branch allowlists, test and review gates, signed provenance, and human approval
before publication. It must not reuse host-operation authority or GitHub issue credentials
for source writes.

## External Contract References

- GitHub recommends granting an app only the permissions it needs:
  <https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app>
- Creating an issue accepts GitHub App installation tokens and fine-grained tokens with
  Issues repository permission (write):
  <https://docs.github.com/en/rest/issues/issues#create-an-issue>
- GitHub App installations can be restricted to selected repositories:
  <https://docs.github.com/en/apps/using-github-apps/installing-a-github-app-from-a-third-party>
