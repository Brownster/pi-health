import { requestApi } from "@/lib/api";
import { createOperation, streamOperation, type OperationEvent } from "@/lib/operations";

export type AlertKind = "container" | "smart" | "mount" | "snapraid";

export interface AlertSilence {
  kind: AlertKind;
  key: string;
  created_at: string;
  expires_at: string | null;
  reason: string;
}

export interface AlertPolicy {
  version: number;
  categories: Record<AlertKind, { enabled: boolean }>;
  required_mounts: string[];
  silences: AlertSilence[];
}

export interface AlertResource {
  key: string;
  kind: AlertKind;
  ok: boolean;
  severity: "warning" | "critical";
  summary: string;
}

export interface ActiveIncident extends Omit<AlertResource, "ok"> {
  opened_at: string;
  updated_at: string;
  delivered_at: string | null;
}

export interface MattermostStatus {
  state: "not_installed" | "connected" | "degraded" | "disconnected";
  installed: boolean;
  site_url: string | null;
  stack_name: string;
  team: string;
  channel: string;
  webhook_configured: boolean;
  policy: AlertPolicy;
  resources: AlertResource[];
  incidents: ActiveIncident[];
  delivery: { at?: string; ok?: boolean; error?: string | null };
  updated_at: number | null;
  services: Record<string, { state: string; health: string | null }>;
}

export interface MattermostSetup {
  site_url: string;
  admin_username: string;
  admin_email: string;
  admin_password: string;
  stack_name: string;
  team_name: string;
  channel_name: string;
  timezone: string;
  poll_seconds: number;
  fail_threshold: number;
}

export function getMattermostStatus(signal?: AbortSignal): Promise<MattermostStatus> {
  return requestApi<MattermostStatus>("/api/integrations/mattermost", { method: "GET", signal });
}

export async function installMattermost(
  setup: MattermostSetup,
  onEvent: (event: OperationEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const operation = await createOperation(
    "/api/integrations/mattermost/install",
    { ...setup },
    signal,
  );
  await streamOperation(operation.stream_url, onEvent, signal);
}

export async function updateMattermostPolicy(policy: AlertPolicy): Promise<AlertPolicy> {
  const result = await requestApi<{ policy: AlertPolicy }>("/api/integrations/mattermost/policy", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(policy),
  });
  return result.policy;
}

export function sendMattermostTest(): Promise<{ status: string; at: string }> {
  return requestApi<{ status: string; at: string }>("/api/integrations/mattermost/test", {
    method: "POST",
  });
}
