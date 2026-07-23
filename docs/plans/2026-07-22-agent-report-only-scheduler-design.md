# Agent Report-Only Scheduler Design

Date: 2026-07-22

Status: Accepted implementation detail for AO-007

Parent plan: `docs/plans/2026-07-20-agent-operations-autonomy-implementation-plan.md`

## Objective

AO-007 adds scheduled diagnosis without scheduled mutation. An administrator defines a
bounded set of existing `limeops` read operations, a five-field cron expression, an IANA
timezone, a maintenance window, fixed report-only budgets, and the existing Mattermost
alerts channel. Each due occurrence runs through `limeopsd`, stores a bounded report, and
attempts delivery once. The scheduler never calls `action.propose`, the action socket, a
model provider, Docker, the helper, or a domain mutation service.

This release establishes the schedule, occurrence, recovery, and delivery contracts that
AO-009 can later extend for canaried supervised actions. AO-007 rejects every non-zero
action, downtime, retry, or model-invocation budget.

## Schedule Contract

The authenticated Automation API accepts this strict shape:

```json
{
  "name": "Morning health report",
  "enabled": true,
  "checks": [
    {"operation": "system.status", "params": {}},
    {"operation": "service.status", "params": {"unit": "limeopsd"}}
  ],
  "window": {
    "cron": "0 7 * * *",
    "timezone": "Europe/London",
    "duration_minutes": 30
  },
  "budgets": {
    "max_checks": 8,
    "max_reports": 1,
    "max_actions": 0,
    "max_downtime_seconds": 0,
    "max_retries": 0,
    "max_model_invocations": 0
  },
  "delivery": {"channel": "mattermost-alerts", "mode": "immediate"}
}
```

Create assigns a stable UUID, immutable owner, timestamps, and revision. Update requires
the current revision and rejects unknown fields. A schedule contains 1–12 checks, and
`max_checks` must cover the list. AO-007 permits these read operations:

- `system.status`, `container.list`, and `container.status`;
- `stack.list` and `stack.status`;
- `service.status`, `disk.health`, `mount.status`, and `snapraid.status`;
- `network.check`, `installation.inventory`, `packages.status`, and `packages.pending`.

The schedule validator checks each operation's exact parameter shape. The live broker
then applies its own operation and resource policy. Scheduled logs, proposals, findings,
approval decisions, and every unknown operation remain unavailable.

## Persistence and Occurrences

The dashboard owns `/var/lib/limeos/agent-actions/automation.sqlite3`. Separate `schedules`
and `schedule_occurrences` tables keep configuration and execution evidence independent
from the action ledger. A unique `{schedule_id, scheduled_for}` constraint deduplicates
repeated APScheduler ticks. The occurrence ID is derived from that pair, so restarts and
clock replays address the same record.

An occurrence moves through `running`, `report_ready`, `delivering`, and `delivered`.
Known failures end as `check_failed` or `delivery_failed`. Startup reruns a `running`
occurrence because all checks are read-only, and it delivers a persisted `report_ready`
occurrence. Startup changes `delivering` to `delivery_unknown` and does not resend it:
the remote webhook may have accepted the report before the process stopped. This rule
prefers one missing report over a duplicate report.

Each check stores its operation, bounded target, outcome, short summary, audit ID, and
public broker error code. Raw responses and private errors stay out of the automation
database and Mattermost. One failed check does not hide the others; it produces a partial
report. Reports contain at most 12 summaries and use existing redaction before storage and
delivery.

## Scheduling and Delivery

A dedicated background scheduler registers one job per enabled schedule. Jobs use the
configured timezone, coalesce missed ticks, permit one concurrent instance, and use the
maintenance-window duration as their misfire grace period. Create, update, disable, and
startup reconcile the registered jobs from durable schedule state.

The runner calls the local `limeopsd` socket as
`{"type":"system","id":"agent-scheduler","username":null}`. The Unix peer boundary,
read policy, strict operation validator, resource allowlist, timeout, output bound, and
audit writer therefore remain active for every check.

The existing Mattermost integration sends the final report through its secret-managed
alerts webhook. Healthy reports use an informational heading; attention and partial
reports use a warning heading. Delivery failure records a bounded state and never exposes
the webhook or transport exception. A missing Mattermost webhook does not prevent checks
or persistence.

## API and Interface

AO-007 adds:

```text
GET  /api/integrations/agents/automation/schedules
POST /api/integrations/agents/automation/schedules
GET  /api/integrations/agents/automation/schedules/<id>
PUT  /api/integrations/agents/automation/schedules/<id>
```

All routes require authentication, CSRF on mutation, and `extensions.admin`. Responses
use `Cache-Control: no-store`. List and detail responses include the latest bounded
occurrence so an administrator can see the last result and delivery state.

The Automation view keeps authority policy and schedules separate. It shows the
report-only boundary, next run, last occurrence, window, checks, budgets, and delivery
state. The editor offers only the code-owned diagnostic catalogue and fixed zero-write
budgets. It cannot select an action capability or authority mode.

## Verification

Unit tests cover strict validation, timezone and cron rejection, report-only budgets,
occurrence deduplication, partial results, bounded redaction, update conflicts, disable,
restart recovery, and ambiguous delivery. API tests cover authentication, admin roles,
CSRF, no-store responses, and bounded errors. Scheduler adapter tests prove job
reconciliation and maintenance-window options. Frontend tests lock the editable contract,
and browser tests cover schedule creation and disablement.

The target-Pi check keeps the action kill switch engaged, creates one short-lived
report-only schedule, observes one delivered report and one occurrence, restarts the
dashboard, and confirms that no duplicate report or action record appears.
