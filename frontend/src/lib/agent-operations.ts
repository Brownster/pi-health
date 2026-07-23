import { requestApi } from "./api";

export {
  actionCanBeApproved,
  actionCanBeAttested,
  actionCanBeCancelled,
  actionCanBeRejected,
  editableFinding,
  editableRepairSchedule,
  editableSchedule,
  newAgentSchedule,
  newAgentRepairSchedule,
  repairScheduleReady,
  scheduleReady,
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

export interface AgentCanary {
  id: string;
  operation: string;
  target: string;
  trigger: "scheduled";
  capability_version: string;
  risk: "R1";
  source_action_id: string;
  release_commit: string;
  attested_by: AgentActor;
  attested_at: string;
  revoked_by: AgentActor | null;
  revoked_at: string | null;
  status: "eligible" | "stale" | "revoked";
}

export interface AgentCanarySnapshot {
  canaries: AgentCanary[];
  gate: {
    supervised: "canary_required";
    autonomous: "unavailable";
    eligible_count: number;
  };
}

export interface AgentScheduleCheck {
  operation: string;
  params: Record<string, string>;
}

export interface AgentScheduleInput {
  name: string;
  enabled: boolean;
  checks: AgentScheduleCheck[];
  window: {
    cron: string;
    timezone: string;
    duration_minutes: number;
  };
  budgets: {
    max_checks: number;
    max_reports: 1;
    max_actions: 0;
    max_downtime_seconds: 0;
    max_retries: 0;
    max_model_invocations: 0;
  };
  delivery: { channel: "mattermost-alerts"; mode: "immediate" };
}

export interface AgentScheduleOccurrence {
  id: string;
  schedule_id: string;
  scheduled_for: string;
  state: string;
  terminal_code: string | null;
  finished_at: string | null;
}

export interface AgentSchedule extends AgentScheduleInput {
  id: string;
  owner: AgentActor;
  created_at: string;
  updated_at: string;
  revision: number;
  next_run: string | null;
  last_occurrence: AgentScheduleOccurrence | null;
}

export interface AgentDiagnosticCheck {
  operation: string;
  parameter: string | null;
}

export interface AgentScheduleUpdate extends AgentScheduleInput {
  revision: number;
}

export type AgentServicePriority = "critical" | "high" | "normal" | "low";

export interface AgentRepairScheduleInput {
  name: string;
  enabled: boolean;
  operation: "container.restart";
  params: { name: "get_iplayer" };
  service_priority: AgentServicePriority;
  window: {
    cron: string;
    timezone: string;
    duration_minutes: number;
  };
  delivery: { channel: "mattermost-alerts"; mode: "threaded" };
}

export interface AgentSupervisionAssessment {
  id: string;
  schedule_id: string;
  assessed_for: string;
  outcome: "healthy" | "failed" | "unknown";
  code: string;
  observed_status: string | null;
  observed_health: string | null;
  audit_id: string | null;
  recorded_at: string;
}

export interface AgentIncidentTransition {
  id: string;
  incident_id: string;
  type: string;
  assessment_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface AgentSupervisionIncident {
  id: string;
  schedule_id: string;
  operation: string;
  target: string;
  state: string;
  consecutive_failures: number;
  last_assessment_id: string;
  last_action_id: string | null;
  thread_id: string | null;
  opened_at: string;
  updated_at: string;
  resolved_at: string | null;
  terminal_code: string | null;
  revision: number;
  transitions?: AgentIncidentTransition[];
}

export interface AgentDemotion {
  id: string;
  operation: string;
  target: string;
  cause: string;
  source_action_id: string;
  release_commit: string;
  demoted_at: string;
  cleared_by: AgentActor | null;
  cleared_at: string | null;
  recovery_action_id: string | null;
  revision: number;
  active: boolean;
}

export interface AgentRepairScheduleStatus {
  assessments: AgentSupervisionAssessment[];
  incident: AgentSupervisionIncident | null;
  last_action: AgentAction | null;
  canary:
    | (Omit<AgentCanary, "status"> & {
        status: "eligible" | "stale" | "unavailable";
      })
    | null;
  demotion: AgentDemotion | null;
  configured_authority: AgentAuthorityMode;
  effective_authority: AgentAuthorityMode;
  maintenance_window: {
    key: string;
    start: string;
    deadline: string;
  } | null;
  budget: {
    rolling_24h: { used: number; limit: 1 };
    window: { used: number; limit: 1 };
    last_charge: {
      id: string;
      action_id: string;
      charged_at: string;
    } | null;
    cooldown_until: string | null;
  };
}

export interface AgentRepairSchedule extends AgentRepairScheduleInput {
  id: string;
  target: string;
  risk: "R1";
  capability_version: string;
  assessment_operation: "container.status";
  assessment_interval_seconds: 600;
  failure_threshold: 2;
  owner: AgentActor;
  created_at: string;
  updated_at: string;
  revision: number;
  status: AgentRepairScheduleStatus;
}

export interface AgentRepairCatalogueItem {
  operation: "container.restart";
  params: { name: "get_iplayer" };
  target: "get_iplayer";
  risk: "R1";
  capability_version: string;
  assessment_operation: "container.status";
  assessment_interval_seconds: 600;
  failure_threshold: 2;
  budgets: Record<string, number>;
}

export interface AgentRepairScheduleUpdate extends AgentRepairScheduleInput {
  revision: number;
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

export function getAgentCanaries(signal?: AbortSignal): Promise<AgentCanarySnapshot> {
  return requestApi("/api/integrations/agents/canaries", {
    method: "GET",
    signal,
  });
}

export async function attestAgentCanary(actionId: string): Promise<AgentCanary> {
  const response = await requestApi<{ canary: AgentCanary }>(
    `/api/integrations/agents/actions/${encodeURIComponent(actionId)}/canary`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    },
  );
  return response.canary;
}

export async function revokeAgentCanary(attestationId: string): Promise<AgentCanary> {
  const response = await requestApi<{ canary: AgentCanary }>(
    `/api/integrations/agents/canaries/${encodeURIComponent(attestationId)}/revoke`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    },
  );
  return response.canary;
}

export async function getAgentAutomationPolicy(signal?: AbortSignal): Promise<AgentAutomationPolicy> {
  const response = await requestApi<{ policy: AgentAutomationPolicy }>(
    "/api/integrations/agents/automation/policy",
    { method: "GET", signal },
  );
  return response.policy;
}

export async function updateAgentAutomationPolicy(policy: AgentAutomationPolicy): Promise<AgentAutomationPolicy> {
  const response = await requestApi<{ policy: AgentAutomationPolicy }>("/api/integrations/agents/automation/policy", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(policy),
  });
  return response.policy;
}

export function getAgentSchedules(signal?: AbortSignal): Promise<{
  schedules: AgentSchedule[];
  diagnostic_catalogue: AgentDiagnosticCheck[];
}> {
  return requestApi("/api/integrations/agents/automation/schedules", {
    method: "GET",
    signal,
  });
}

export async function createAgentSchedule(schedule: AgentScheduleInput): Promise<AgentSchedule> {
  const response = await requestApi<{ schedule: AgentSchedule }>(
    "/api/integrations/agents/automation/schedules",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(schedule),
    },
  );
  return response.schedule;
}

export async function updateAgentSchedule(
  id: string,
  schedule: AgentScheduleUpdate,
): Promise<AgentSchedule> {
  const response = await requestApi<{ schedule: AgentSchedule }>(
    `/api/integrations/agents/automation/schedules/${encodeURIComponent(id)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(schedule),
    },
  );
  return response.schedule;
}

export function getAgentRepairSchedules(signal?: AbortSignal): Promise<{
  schedules: AgentRepairSchedule[];
  catalogue: AgentRepairCatalogueItem[];
  service_priorities: AgentServicePriority[];
  limits: {
    max_actions_per_target_24h: 1;
    max_actions_per_window: 1;
  };
}> {
  return requestApi("/api/integrations/agents/automation/repairs", {
    method: "GET",
    signal,
  });
}

export async function createAgentRepairSchedule(
  schedule: AgentRepairScheduleInput,
): Promise<AgentRepairSchedule> {
  const response = await requestApi<{ schedule: AgentRepairSchedule }>(
    "/api/integrations/agents/automation/repairs",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(schedule),
    },
  );
  return response.schedule;
}

export async function updateAgentRepairSchedule(
  id: string,
  schedule: AgentRepairScheduleUpdate,
): Promise<AgentRepairSchedule> {
  const response = await requestApi<{ schedule: AgentRepairSchedule }>(
    `/api/integrations/agents/automation/repairs/${encodeURIComponent(id)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(schedule),
    },
  );
  return response.schedule;
}

export async function enableAgentRepairSchedule(
  id: string,
  revision: number,
): Promise<AgentRepairSchedule> {
  const response = await requestApi<{ schedule: AgentRepairSchedule }>(
    `/api/integrations/agents/automation/repairs/${encodeURIComponent(id)}/enable`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        revision,
        confirmation: "ENABLE SUPERVISION",
      }),
    },
  );
  return response.schedule;
}

export function getAgentSupervisionIncidents(
  limit = 50,
  signal?: AbortSignal,
): Promise<{ incidents: AgentSupervisionIncident[] }> {
  return requestApi(
    `/api/integrations/agents/automation/incidents?limit=${limit}`,
    { method: "GET", signal },
  );
}

export function getAgentDemotions(
  limit = 50,
  signal?: AbortSignal,
): Promise<{ demotions: AgentDemotion[] }> {
  return requestApi(
    `/api/integrations/agents/automation/demotions?limit=${limit}`,
    { method: "GET", signal },
  );
}

export async function clearAgentDemotion(
  id: string,
  values: {
    revision: number;
    recovery_action_id: string;
    confirmation: "CLEAR DEMOTION";
  },
): Promise<AgentDemotion> {
  const response = await requestApi<{ demotion: AgentDemotion }>(
    `/api/integrations/agents/automation/demotions/${encodeURIComponent(id)}/clear`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    },
  );
  return response.demotion;
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
