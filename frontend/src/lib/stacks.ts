import { requestApi, toNullableNumber, toNullableString } from "@/lib/api";

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

export interface StackActionResult {
  success?: boolean;
  stdout?: string;
  stderr?: string;
  returncode?: number;
  error?: string;
}

export interface StackLogsResult {
  logs: string;
  returncode: number | null;
}

export async function runStackAction(
  name: string,
  action: StackAction,
  signal?: AbortSignal,
): Promise<StackActionResult> {
  const payload = await requestApi<StackActionResult>(
    `/api/stacks/${encodeURIComponent(name)}/${action}`,
    { method: "POST", signal },
  );

  if (payload.error) {
    throw new Error(payload.error);
  }
  return payload;
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

/** SSE endpoint (GET) for streamed `docker compose` output; consumed via EventSource. */
export function getStackStreamUrl(name: string, action: StackAction): string {
  return `/api/stacks/${encodeURIComponent(name)}/${action}/stream`;
}

export function getStackServicesPercent(stack: StackSummary): number | null {
  if (stack.container_count === null || stack.container_count <= 0 || stack.running_count === null) {
    return null;
  }
  return Math.round((stack.running_count / stack.container_count) * 100);
}
