import type { AgentAction, AgentFinding, AgentFindingContent } from "./agent-operations";

export function editableFinding(finding: AgentFinding): AgentFindingContent {
  return {
    kind: finding.kind,
    title: finding.title,
    summary: finding.summary,
    component: finding.component,
    affected_version: finding.affected_version,
    expected_behavior: finding.expected_behavior,
    actual_behavior: finding.actual_behavior,
    reproduction_steps: [...finding.reproduction_steps],
    impact: finding.impact,
    frequency: finding.frequency,
    workaround: finding.workaround,
    confidence: finding.confidence,
    acceptance_criteria: [...finding.acceptance_criteria],
    source_type: finding.source_type,
  };
}

export function actionCanBeApproved(action: AgentAction): boolean {
  return action.state === "awaiting_approval" && action.authority_mode === "approval";
}

export function actionCanBeRejected(action: AgentAction): boolean {
  return action.state === "proposed" || action.state === "awaiting_approval";
}

export function actionCanBeCancelled(action: AgentAction): boolean {
  return ["proposed", "awaiting_approval", "authorised"].includes(action.state);
}
