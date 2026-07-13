import { requestApi } from "@/lib/api";
import {
  createOperation,
  streamOperation,
  type OperationCreated,
  type OperationEvent,
} from "@/lib/operations";

export type AgentState =
  | "not_installed"
  | "setup_required"
  | "authenticating"
  | "connected"
  | "degraded"
  | "disabled"
  | "disconnected";

export interface AgentStatus {
  state: AgentState;
  installed: boolean;
  enabled: boolean;
  mattermost: {
    state: string;
    site_url: string | null;
    team: string | null;
    channel: string | null;
  };
  gateway: { state: string; broker_state: string };
  provider: {
    id: "claude";
    installed: boolean;
    version: string | null;
    compatible: boolean;
    authenticated: boolean;
  };
  last_successful_turn?: AgentUsageRecord | null;
}

export interface AgentProvider {
  id: "claude";
  name: string;
  installed: boolean;
  version: string | null;
  authenticated: boolean;
  compatible: boolean;
  state: AgentState;
}

export interface AgentPermissions {
  profile: "read_only";
  allowed_operations: string[];
  resources: Record<string, string[]>;
  denied_capabilities: string[];
}

export interface AgentUsageRecord {
  at?: string;
  conversation_id?: string;
  correlation_id?: string;
  outcome?: "ok" | "error" | "busy" | "limit";
  rounds?: number;
  duration_seconds?: number;
  tool_operations?: string[];
  tool_audit_ids?: string[];
}

export interface AgentUsage {
  totals: {
    total_turns?: number;
    total_invocations?: number;
    invocations_today?: number;
  };
  records: AgentUsageRecord[];
}

export interface AgentAuditRecord {
  ts?: string;
  phase?: string;
  request_id?: string;
  audit_id?: string;
  operation?: string;
  actor_type?: string;
  actor_id?: string;
  actor_username?: string;
  ok?: boolean;
  error_code?: string;
  duration_ms?: number;
  output_bytes?: number;
}

export interface AgentAudit {
  records: AgentAuditRecord[];
}

export interface AgentInstallValues {
  admin_username: string;
  admin_password: string;
  limits?: {
    turn_timeout_seconds: number;
    tool_rounds_per_turn: number;
    invocations_per_day: number;
  };
}

export function getAgentStatus(signal?: AbortSignal): Promise<AgentStatus> {
  return requestApi<AgentStatus>("/api/integrations/agents", { method: "GET", signal });
}

export function getAgentProviders(signal?: AbortSignal): Promise<{ providers: AgentProvider[] }> {
  return requestApi<{ providers: AgentProvider[] }>("/api/integrations/agents/providers", {
    method: "GET",
    signal,
  });
}

export function getAgentPermissions(signal?: AbortSignal): Promise<AgentPermissions> {
  return requestApi<AgentPermissions>("/api/integrations/agents/permissions", {
    method: "GET",
    signal,
  });
}

export function getAgentUsage(limit = 50, signal?: AbortSignal): Promise<AgentUsage> {
  return requestApi<AgentUsage>(`/api/integrations/agents/usage?limit=${limit}`, {
    method: "GET",
    signal,
  });
}

export function getAgentAudit(limit = 50, signal?: AbortSignal): Promise<AgentAudit> {
  return requestApi<AgentAudit>(`/api/integrations/agents/audit?limit=${limit}`, {
    method: "GET",
    signal,
  });
}

async function runAgentOperation(
  path: string,
  body: Record<string, unknown>,
  onEvent: (event: OperationEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const operation = await createOperation(path, body, signal);
  await streamOperation(operation.stream_url, onEvent, signal);
}

export function installAgents(
  values: AgentInstallValues,
  onEvent: (event: OperationEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return runAgentOperation(
    "/api/integrations/agents/install",
    values as unknown as Record<string, unknown>,
    onEvent,
    signal,
  );
}

export function repairAgents(
  values: Partial<Pick<AgentInstallValues, "admin_username" | "admin_password">>,
  onEvent: (event: OperationEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return runAgentOperation(
    "/api/integrations/agents/repair",
    values,
    onEvent,
    signal,
  );
}

export function startClaudeAuth(signal?: AbortSignal): Promise<OperationCreated> {
  return createOperation(
    "/api/integrations/agents/providers/claude/auth",
    { action: "start" },
    signal,
  );
}

export function streamClaudeAuth(
  streamUrl: string,
  onEvent: (event: OperationEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamOperation(streamUrl, onEvent, signal);
}

export function submitClaudeAuth(operationId: string, code: string): Promise<{ accepted: true }> {
  return requestApi<{ accepted: true }>("/api/integrations/agents/providers/claude/auth", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "submit", operation_id: operationId, code }),
  });
}

export function cancelClaudeAuth(operationId: string): Promise<{ cancelled: true }> {
  return requestApi<{ cancelled: true }>("/api/integrations/agents/providers/claude/auth", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "cancel", operation_id: operationId }),
  });
}

export function disableAgents(): Promise<{ state: "disabled" }> {
  return requestApi<{ state: "disabled" }>("/api/integrations/agents/disable", {
    method: "POST",
  });
}

export function sendAgentTest(): Promise<{ status: "sent" }> {
  return requestApi<{ status: "sent" }>("/api/integrations/agents/test", {
    method: "POST",
  });
}
