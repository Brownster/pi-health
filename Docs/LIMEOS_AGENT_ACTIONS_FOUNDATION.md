# LimeOS Agent Actions Foundation

Date: 2026-07-21

Status: Implemented with all mutations disabled by default

## Shipped Scope

The assistant can diagnose the host, create exact repair proposals, and draft private
bug or feature findings. Only the isolated actuator can change Docker state. The first
write capabilities are `container.start` and `container.restart`.

The release does not grant the model a shell, Docker socket, helper socket, arbitrary
filesystem access, GitHub credential, or actuator-socket access. It does not publish
issues, create branches, or open pull requests.

## Trust Boundaries

The model-facing `limeos-agent` process calls the ordinary `limeopsd` broker. That
broker accepts reads plus `action.propose` and `finding.propose`. A proposal records an
operation, normalized parameters, target, reason, evidence IDs, actor ID, payload hash,
precondition hash, expiry, and policy decision.

The `limeops-action-worker` forwards only an authorised action ID. The
`limeops-actuatord` process reloads policy and rechecks the kill switch, contract
version, target, payload hash, approval, expiry, and live precondition before it calls
`ContainerOperationsService.control`. It then checks container state and health. A
restart must also produce a new start timestamp.

The service boundary uses these paths:

| Purpose | Path |
| --- | --- |
| Proposal/read policy | `/etc/limeos/agent-policy.json` |
| Authority and target policy | `/etc/limeos/agent-action-policy.json` |
| Action-broker request policy | `/etc/limeos/agent-actuator-policy.json` |
| Read socket | `/run/limeos/limeops.sock` |
| Action socket | `/run/limeos-actions/actions.sock` |
| Action and finding state | `/var/lib/limeos/agent-actions/` |
| Action audit | `/var/log/limeos/agent-action-audit.jsonl` |

`lime-agent` belongs to `limeops-client`; it does not belong to `limeops-action`,
`docker`, or `pihealth`. Its systemd sandbox also marks `/run/limeos-actions`
inaccessible.

## Default State

The shipped action policy sets `kill_switch` to `true`. Both registered operations are
disabled and have empty target maps. Installation or upgrade therefore changes no host
state until an administrator edits the action policy.

Keep this default through deployment tests. Confirm that reads and local findings work,
that action proposals fail closed, and that the agent process cannot open the action
socket.

## Enable One Approval-Bound Canary

Choose a non-critical container. Record its exact Docker name and the immutable ID of
each eligible approver. For a dashboard administrator named `admin`, use `local:admin`.
For a Mattermost approver, use `mattermost:<user-id>`, never a username.

Set a single target to approval mode and leave scheduled and event triggers in observe
mode:

```json
{
  "schema_version": "1",
  "kill_switch": false,
  "defaults": {
    "proposal_ttl_seconds": 900
  },
  "operations": {
    "container.start": {
      "enabled": false,
      "approvers": [],
      "targets": {}
    },
    "container.restart": {
      "enabled": true,
      "approvers": ["local:admin"],
      "targets": {
        "jellyfin-canary": {
          "interactive": "approval",
          "scheduled": "observe",
          "event": "observe"
        }
      }
    }
  }
}
```

Write the file atomically as root, preserve mode `0640` and ownership
`root:pihealth`, then validate it without executing an action:

```text
/usr/bin/python3 -m agent_actions.server --check
```

Policy reloads on each proposal, approval, and execution. A service restart is not
required after an atomic policy update.

## Approval and Execution

The authenticated API exposes:

```text
GET  /api/integrations/agents/actions/capabilities
GET  /api/integrations/agents/actions
GET  /api/integrations/agents/actions/<id>
POST /api/integrations/agents/actions/<id>/approve
POST /api/integrations/agents/actions/<id>/reject
POST /api/integrations/agents/actions/<id>/cancel
GET  /api/integrations/agents/automation/policy
PUT  /api/integrations/agents/automation/policy
```

Reads require `capability.view`; approval and rejection require `extensions.admin` and
CSRF protection. Approval, rejection, and cancellation accept an empty body. The queue
worker detects the authorised record, sends only its ID to the action broker, and
consumes the approval in the same transaction that changes the state to `executing`.
Action detail includes the bounded lifecycle event history.

Policy reads and writes require `extensions.admin`. The application validates the exact
code-owned operation catalogue before the privileged helper atomically replaces the
file. This release accepts observe, propose, and approval modes. It rejects supervised
and autonomous policy updates until the repair canary gate records the required evidence.

Treat `succeeded` as the only successful terminal state. `execution_failed`,
`verification_failed`, `precondition_changed`, `expired`, and `rejected` require review.
The initial container actions have no safe automatic rollback because container stop is
outside the allowlist.

When a Mattermost turn creates a proposal, the listener posts a separate bounded card in
the originating thread with the operation, exact target, risk, reason, expected impact,
expiry, and action ID. An eligible user reacts with :white_check_mark: to approve once or
:x: to reject. Proposal-post bindings and reaction deduplication survive listener
restarts. The listener forwards the immutable reacting user and channel IDs through
typed `action.approve` or `action.reject` broker controls. Those controls are omitted
from the provider context and gateway allowlist, so neither the model nor prompt content
can invoke them. The action policy rechecks the actor allowlist and current proposal
state before recording the decision.

## Private Findings

The agent can call `finding.propose` for a bug, feature request, maintenance gap, or
documentation gap. The service validates every field, redacts common secret patterns,
deduplicates drafts by fingerprint, stores evidence references, and records the immutable
source actor.

Administrators can review, edit, or reject drafts:

```text
GET  /api/integrations/agents/findings
GET  /api/integrations/agents/findings/<id>
PUT  /api/integrations/agents/findings/<id>
POST /api/integrations/agents/findings/<id>/reject
```

The AI Agents card exposes the same bounded controls in the browser. Its **Actions** tab
shows the immutable proposal, exact target, reason, expected impact, evidence references,
expiry, verified parameters, and lifecycle history before offering a valid approve,
reject, or cancel transition. **Findings** keeps redacted drafts private while allowing
administrators to edit or reject them. **Automation** edits only registered operations,
exact target allowlists, approver actor IDs, proposal expiry, and the emergency kill
switch. It offers observe, propose, and approval modes; later authority levels remain
server-rejected until the repair canary gate is complete.

This release has no publication endpoint. Every finding returns `publication: null`.
GitHub issue publication will use a separate repository allowlist, credential, preview,
and fresh approval in AO-016. Pull requests remain deferred.

## Emergency Stop and Rollback

Stop new execution first:

```text
systemctl stop limeops-action-worker.service
```

Set `kill_switch` to `true` in `/etc/limeos/agent-action-policy.json`. The actuator will
deny any queued action when it revalidates policy. Leave `limeopsd` and `limeos-agent`
running so diagnosis, alerts, and local findings remain available.

If needed, stop `limeops-actuatord.service` and remove access to
`/run/limeos-actions/actions.sock`. Preserve `/var/lib/limeos/agent-actions` and both
agent audit logs for incident review.

## Current Limits

This slice completes the action foundation and the first two repair adapters. It does
not yet include stack or integration repair, report-only schedules, maturity promotion,
cooldowns, disruption budgets, installation, configuration, review experiments,
optimisation, or GitHub publication. Those features remain gated by the accepted
implementation plan and target-Pi canary evidence.
