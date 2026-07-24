import assert from "node:assert/strict";
import test from "node:test";

import {
  actionCanBeApproved,
  actionCanBeAttested,
  actionCanBeCancelled,
  actionCanBeRejected,
  editableFinding,
  editableRepairSchedule,
  editableSchedule,
  newAgentRepairSchedule,
  newAgentSchedule,
  repairScheduleReady,
  scheduleReady,
} from "../src/lib/agent-operations-contract.ts";
import type {
  AgentAction,
  AgentFinding,
  AgentRepairSchedule,
  AgentSchedule,
} from "../src/lib/agent-operations.ts";

function action(state: AgentAction["state"], authority_mode: AgentAction["authority_mode"] = "approval"): AgentAction {
  return { state, authority_mode } as AgentAction;
}

test("action controls expose only valid pre-execution transitions", () => {
  assert.equal(actionCanBeApproved(action("awaiting_approval")), true);
  assert.equal(actionCanBeApproved(action("awaiting_approval", "propose")), false);
  assert.equal(actionCanBeRejected(action("proposed")), true);
  assert.equal(actionCanBeRejected(action("authorised")), false);
  assert.equal(actionCanBeCancelled(action("authorised")), true);
  assert.equal(actionCanBeCancelled(action("executing")), false);
  assert.equal(actionCanBeCancelled(action("succeeded")), false);
});

test("repair canary requires one verified interactive approval action", () => {
  const eligible = {
    ...action("succeeded"),
    terminal_code: "verified",
    risk: "R1",
    trigger: "interactive",
    events: [{ phase: "succeeded" }],
  } as AgentAction;

  assert.equal(actionCanBeAttested(eligible), true);
  assert.equal(actionCanBeAttested({ ...eligible, risk: "R2" }), false);
  assert.equal(actionCanBeAttested({ ...eligible, trigger: "scheduled" }), false);
  assert.equal(actionCanBeAttested({
    ...eligible,
    events: [...(eligible.events ?? []), { phase: "canary_attested" }],
  } as AgentAction), false);
});

test("finding editor receives only mutable content and independent lists", () => {
  const finding = {
    id: "finding-1",
    fingerprint: "private",
    state: "draft",
    kind: "bug",
    title: "Repair verification gap",
    summary: "A repair completed without a health check.",
    component: "agent-actions",
    affected_version: "1.0",
    expected_behavior: "Verify health.",
    actual_behavior: "Returned early.",
    reproduction_steps: ["Run repair."],
    impact: "False recovery signal.",
    frequency: "Once",
    workaround: "Check manually.",
    confidence: "high",
    acceptance_criteria: ["Wait for health."],
    source_type: "failed_action",
    evidence_ids: ["audit-1"],
    actor: { type: "system", id: "agent", username: null },
    redaction_applied: true,
    created_at: "2026-07-21T10:00:00Z",
    updated_at: "2026-07-21T10:00:00Z",
    revision: 1,
    publication: null,
  } satisfies AgentFinding;

  const editable = editableFinding(finding);
  editable.reproduction_steps.push("Verify the result.");

  assert.equal("evidence_ids" in editable, false);
  assert.deepEqual(finding.reproduction_steps, ["Run repair."]);
  assert.equal(editable.title, finding.title);
});

test("schedule editor is report-only and copies mutable nested values", () => {
  const created = newAgentSchedule();
  assert.equal(created.budgets.max_actions, 0);
  assert.equal(created.budgets.max_model_invocations, 0);
  assert.equal(created.delivery.channel, "mattermost-alerts");
  assert.equal(scheduleReady(created), false);
  created.name = "Morning report";
  assert.equal(scheduleReady(created), true);

  const schedule = {
    ...created,
    id: "schedule-1",
    owner: { type: "local", id: "admin", username: "admin" },
    created_at: "2026-07-22T07:00:00Z",
    updated_at: "2026-07-22T07:00:00Z",
    revision: 3,
    next_run: "2026-07-23T07:00:00Z",
    last_occurrence: null,
  } satisfies AgentSchedule;
  const editable = editableSchedule(schedule);
  editable.checks[0].operation = "disk.health";

  assert.equal(schedule.checks[0].operation, "system.status");
  assert.equal(editable.revision, 3);
  assert.equal("owner" in editable, false);
});

test("supervised repair schedules start disabled and copy mutable fields", () => {
  const created = newAgentRepairSchedule();
  assert.equal(created.enabled, false);
  assert.deepEqual(created.params, { name: "get_iplayer" });
  assert.equal(created.delivery.mode, "threaded");
  assert.equal(repairScheduleReady(created), true);

  const schedule = {
    ...created,
    id: "repair-1",
    target: "get_iplayer",
    risk: "R1",
    capability_version: "1",
    assessment_operation: "container.status",
    assessment_interval_seconds: 600,
    failure_threshold: 2,
    owner: { type: "local", id: "admin", username: "admin" },
    created_at: "2026-07-23T10:00:00Z",
    updated_at: "2026-07-23T10:00:00Z",
    revision: 3,
    status: {},
  } as AgentRepairSchedule;
  const editable = editableRepairSchedule(schedule);
  editable.params.name = "get_iplayer";
  editable.window.duration_minutes = 90;

  assert.equal(schedule.window.duration_minutes, 60);
  assert.equal(editable.revision, 3);
  assert.equal("owner" in editable, false);
});
