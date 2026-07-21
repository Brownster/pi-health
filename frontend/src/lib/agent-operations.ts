import { requestApi } from "./api";

export {
  actionCanBeApproved,
  actionCanBeCancelled,
  actionCanBeRejected,
  editableFinding,
} from "./agent-operations-contract";

export type AgentActionState =
  | "proposed"
  | "awaiting_approval"
  | "authorised"
  | "executing"
  | "verifying"
  | "succeeded"
  | "execution_failed"
  | "verification_failed"
  | "rolling_back"
  | "rolled_back"
  | "rollback_failed"
  | "escalation_required"
  | "rejected"
  | "expired"
  | "cancelled"
  | "superseded"
  | "precondition_changed";

export interface AgentActor {
  type: "local" | "mattermost" | "system";
  id: string;
  username: string | null;
}

export interface AgentActionEvent {
  phase: string;
  created_at: string;
  details: Record<string, unknown>;
}

export interface AgentAction {
  id: string;
  operation: string;
  capability_version: string;
  target: string;
  risk: "R0" | "R1" | "R2" | "R3";
  trigger: "interactive" | "scheduled" | "event";
  authority_mode: AgentAuthorityMode;
  params: Record<string, unknown>;
  evidence_ids: string[];
  payload_hash: string;
  reason: string;
  impact: string;
  state: AgentActionState;
  created_at: string;
  expires_at: string;
  actor: AgentActor;
  approval: {
    actor: AgentActor;
    approved_at: string;
    used_at: string | null;
  } | null;
  terminal_code: string | null;
  revision: number;
  events?: AgentActionEvent[];
}

export type AgentAuthorityMode =
  | "observe"
  | "propose"
  | "approval"
  | "supervised"
  | "autonomous";

export interface AgentActionCapability {
  operation: string;
  version: string;
  risk: "R0" | "R1" | "R2" | "R3";
  eligible_modes: AgentAuthorityMode[];
  policy: {
    enabled: boolean;
    targets: Record<string, AgentTargetPolicy>;
  };
}

export interface AgentTargetPolicy {
  interactive: AgentAuthorityMode;
  scheduled: AgentAuthorityMode;
  event: AgentAuthorityMode;
}

export interface AgentOperationPolicy {
  enabled: boolean;
  approvers: string[];
  targets: Record<string, AgentTargetPolicy>;
}

export interface AgentAutomationPolicy {
  schema_version: "1";
  kill_switch: boolean;
  defaults: { proposal_ttl_seconds: number };
  operations: Record<string, AgentOperationPolicy>;
}

export type AgentFindingKind =
  | "bug"
  | "feature_request"
  | "maintenance_gap"
  | "documentation_gap";

export interface AgentFindingContent {
  kind: AgentFindingKind;
  title: string;
  summary: string;
  component: string;
  affected_version: string;
  expected_behavior: string;
  actual_behavior: string;
  reproduction_steps: string[];
  impact: string;
  frequency: string;
  workaround: string;
  confidence: "low" | "medium" | "high";
  acceptance_criteria: string[];
  source_type:
    | "user_discussion"
    | "failed_action"
    | "recurring_incident"
    | "review"
    | "manual";
}

export interface AgentFinding extends AgentFindingContent {
  id: string;
  fingerprint: string;
  state: "draft" | "rejected";
  evidence_ids: string[];
  actor: AgentActor;
  redaction_applied: boolean;
  created_at: string;
  updated_at: string;
  revision: number;
  publication: null;
}

export function getAgentActions(limit = 50, signal?: AbortSignal): Promise<{ actions: AgentAction[] }> {
  return requestApi(`/api/integrations/agents/actions?limit=${limit}`, { method: "GET", signal });
}

export function getAgentAction(id: string, signal?: AbortSignal): Promise<AgentAction> {
  return requestApi(`/api/integrations/agents/actions/${encodeURIComponent(id)}`, { method: "GET", signal });
}

export function approveAgentAction(id: string): Promise<AgentAction> {
  return mutateAgentAction(id, "approve");
}

export function rejectAgentAction(id: string): Promise<AgentAction> {
  return mutateAgentAction(id, "reject");
}

export function cancelAgentAction(id: string): Promise<AgentAction> {
  return mutateAgentAction(id, "cancel");
}

function mutateAgentAction(id: string, action: "approve" | "reject" | "cancel"): Promise<AgentAction> {
  return requestApi(`/api/integrations/agents/actions/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}

export function getAgentActionCapabilities(signal?: AbortSignal): Promise<{
  capabilities: AgentActionCapability[];
  kill_switch: boolean;
}> {
  return requestApi("/api/integrations/agents/actions/capabilities", { method: "GET", signal });
}

export function getAgentAutomationPolicy(signal?: AbortSignal): Promise<AgentAutomationPolicy> {
  return requestApi("/api/integrations/agents/automation/policy", { method: "GET", signal });
}

export function updateAgentAutomationPolicy(policy: AgentAutomationPolicy): Promise<AgentAutomationPolicy> {
  return requestApi("/api/integrations/agents/automation/policy", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(policy),
  });
}

export function getAgentFindings(limit = 50, signal?: AbortSignal): Promise<{ findings: AgentFinding[] }> {
  return requestApi(`/api/integrations/agents/findings?limit=${limit}`, { method: "GET", signal });
}

export function getAgentFinding(id: string, signal?: AbortSignal): Promise<AgentFinding> {
  return requestApi(`/api/integrations/agents/findings/${encodeURIComponent(id)}`, { method: "GET", signal });
}

export function updateAgentFinding(id: string, finding: AgentFindingContent): Promise<AgentFinding> {
  return requestApi(`/api/integrations/agents/findings/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(finding),
  });
}

export function rejectAgentFinding(id: string): Promise<AgentFinding> {
  return requestApi(`/api/integrations/agents/findings/${encodeURIComponent(id)}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}
