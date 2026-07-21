import assert from "node:assert/strict";
import test from "node:test";

import {
  actionCanBeApproved,
  actionCanBeCancelled,
  actionCanBeRejected,
  editableFinding,
} from "../src/lib/agent-operations-contract.ts";
import type { AgentAction, AgentFinding } from "../src/lib/agent-operations.ts";

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
