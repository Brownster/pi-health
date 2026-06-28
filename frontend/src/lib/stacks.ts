import { requestApi, toNullableNumber, toNullableString } from "@/lib/api";
import {
  createOperation,
  type OperationCreated,
  type OperationEvent,
  streamOperation,
} from "@/lib/operations";

export interface StackSummary {
  name: string;
  status: string;
  running_count: number | null;
  container_count: number | null;
  path: string | null;
  compose_file: string | null;
}

interface FetchStacksOptions {
  includeStatus?: boolean;
  signal?: AbortSignal;
}

function normalizeStack(stack: Partial<StackSummary> | undefined): StackSummary {
  return {
    name: String(stack?.name ?? "unknown"),
    status: String(stack?.status ?? "unknown"),
    running_count: toNullableNumber(stack?.running_count),
    container_count: toNullableNumber(stack?.container_count),
    path: toNullableString(stack?.path),
    compose_file: toNullableString(stack?.compose_file),
  };
}

export async function fetchStacks(
  options: FetchStacksOptions = {},
): Promise<StackSummary[]> {
  const includeStatus = options.includeStatus ?? true;
  const payload = await requestApi<{ stacks?: Partial<StackSummary>[]; error?: string }>(
    `/api/stacks?status=${includeStatus ? "true" : "false"}`,
    {
      method: "GET",
      signal: options.signal,
    },
  );

  if (payload.error) {
    throw new Error(payload.error);
  }

  return Array.isArray(payload.stacks) ? payload.stacks.map((item) => normalizeStack(item)) : [];
}

export type StackAction = "up" | "down" | "restart" | "pull";

export type StackOperationEvent = OperationEvent;

export interface StackLogsResult {
  logs: string;
  returncode: number | null;
}

export async function createStackOperation(
  name: string,
  action: StackAction,
  signal?: AbortSignal,
): Promise<OperationCreated> {
  return createOperation(
    `/api/stacks/${encodeURIComponent(name)}/operations`,
    { action },
    signal,
  );
}

export async function fetchStackLogs(
  name: string,
  tail = 200,
  signal?: AbortSignal,
): Promise<StackLogsResult> {
  const payload = await requestApi<{ logs?: string; returncode?: number; error?: string }>(
    `/api/stacks/${encodeURIComponent(name)}/logs?tail=${tail}`,
    { method: "GET", signal },
  );

  if (payload.error) {
    throw new Error(payload.error);
  }
  return {
    logs: payload.logs ?? "",
    returncode: toNullableNumber(payload.returncode),
  };
}

export async function streamStackOperation(
  streamUrl: string,
  onEvent: (event: StackOperationEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamOperation(streamUrl, onEvent, signal);
}

export interface StackComposeResult {
  content: string;
  filename: string | null;
}

export interface StackEnvResult {
  content: string;
  exists: boolean;
}

export async function fetchStackCompose(name: string, signal?: AbortSignal): Promise<StackComposeResult> {
  const payload = await requestApi<{ content?: string; filename?: string; error?: string }>(
    `/api/stacks/${encodeURIComponent(name)}/compose`,
    { method: "GET", signal },
  );
  if (payload.error) {
    throw new Error(payload.error);
  }
  return { content: payload.content ?? "", filename: toNullableString(payload.filename) };
}

export async function saveStackCompose(name: string, content: string, signal?: AbortSignal): Promise<void> {
  const payload = await requestApi<{ status?: string; error?: string }>(
    `/api/stacks/${encodeURIComponent(name)}/compose`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
      signal,
    },
  );
  if (payload.error) {
    throw new Error(payload.error);
  }
}

export async function fetchStackEnv(name: string, signal?: AbortSignal): Promise<StackEnvResult> {
  const payload = await requestApi<{ content?: string; exists?: boolean; error?: string }>(
    `/api/stacks/${encodeURIComponent(name)}/env`,
    { method: "GET", signal },
  );
  if (payload.error) {
    throw new Error(payload.error);
  }
  return { content: payload.content ?? "", exists: Boolean(payload.exists) };
}

export async function saveStackEnv(name: string, content: string, signal?: AbortSignal): Promise<void> {
  const payload = await requestApi<{ status?: string; error?: string }>(
    `/api/stacks/${encodeURIComponent(name)}/env`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
      signal,
    },
  );
  if (payload.error) {
    throw new Error(payload.error);
  }
}

export async function fetchStackBackups(name: string, signal?: AbortSignal): Promise<string[]> {
  const payload = await requestApi<{ backups?: unknown[]; error?: string }>(
    `/api/stacks/${encodeURIComponent(name)}/backups`,
    { method: "GET", signal },
  );
  if (payload.error) {
    throw new Error(payload.error);
  }
  return Array.isArray(payload.backups)
    ? payload.backups.map((item) => String(item)).filter((item) => item.length > 0)
    : [];
}

export async function restoreStackBackup(name: string, backup: string, signal?: AbortSignal): Promise<void> {
  const payload = await requestApi<{ status?: string; error?: string }>(
    `/api/stacks/${encodeURIComponent(name)}/restore`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backup }),
      signal,
    },
  );
  if (payload.error) {
    throw new Error(payload.error);
  }
}

export function getStackServicesPercent(stack: StackSummary): number | null {
  if (stack.container_count === null || stack.container_count <= 0 || stack.running_count === null) {
    return null;
  }
  return Math.round((stack.running_count / stack.container_count) * 100);
}
