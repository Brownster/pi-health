import { requestApi } from "@/lib/api";
import { createOperation, streamOperation, type OperationEvent } from "@/lib/operations";
import {
  lifecycleContractFields,
  type IntegrationLifecycleStatus,
} from "@/lib/integration-lifecycle-contract";

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

export interface MattermostStatus extends IntegrationLifecycleStatus {
  state: "cleanup_required" | "retained_data" | "not_installed" | "connected" | "degraded" | "disabled" | "disconnected";
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

export async function getMattermostStatus(signal?: AbortSignal): Promise<MattermostStatus> {
  const status = await requestApi<MattermostStatus>("/api/integrations/mattermost", { method: "GET", signal });
  return { ...status, ...lifecycleContractFields("mattermost", status) };
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
  await streamOperation(
    operation.stream_url,
    (event) => {
      onEvent(event);
      if (event.error) {
        throw new Error(event.error);
      }
    },
    signal,
  );
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

export interface PendingPackageUpdate {
  name: string;
  installed: string | null;
  candidate: string;
  critical: boolean;
  approved: boolean;
}

export function getPendingPackageUpdates(
  signal?: AbortSignal,
): Promise<{ pending: PendingPackageUpdate[]; approvals: unknown[] }> {
  return requestApi<{ pending: PendingPackageUpdate[]; approvals: unknown[] }>(
    "/api/integrations/packages/pending",
    { method: "GET", signal },
  );
}

export function approvePackageUpdate(
  name: string,
  version: string,
): Promise<{ approval: { name: string; version: string; approved_by: string; approved_at: string } }> {
  return requestApi("/api/integrations/packages/approve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, version }),
  });
}

export interface StackNotificationsStatus {
  enabled: boolean;
  configured: boolean;
  mode: "quiet" | "verbose";
  source_default: string;
  channel_name: string | null;
  token: string | null;
}

export function getStackNotificationsStatus(
  signal?: AbortSignal,
): Promise<StackNotificationsStatus> {
  return requestApi<StackNotificationsStatus>("/api/integrations/stack-notifications", {
    method: "GET",
    signal,
  });
}

export function setStackNotificationsMode(
  mode: "quiet" | "verbose",
): Promise<StackNotificationsStatus> {
  return requestApi<StackNotificationsStatus>("/api/integrations/stack-notifications/mode", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
}

export async function enableStackNotifications(
  adminPassword: string,
  onEvent: (event: OperationEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const operation = await createOperation(
    "/api/integrations/stack-notifications/enable",
    { admin_password: adminPassword },
    signal,
  );
  await streamOperation(
    operation.stream_url,
    (event) => {
      onEvent(event);
      if (event.error) {
        throw new Error(event.error);
      }
    },
    signal,
  );
}
