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

async function requestApi<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    throw new Error(`Request failed (${response.status}) for ${path}`);
  }

  return (await response.json()) as T;
}

function toNullableNumber(value: unknown): number | null {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function toNullableString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
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

export function getStackServicesPercent(stack: StackSummary): number | null {
  if (stack.container_count === null || stack.container_count <= 0 || stack.running_count === null) {
    return null;
  }
  return Math.round((stack.running_count / stack.container_count) * 100);
}
