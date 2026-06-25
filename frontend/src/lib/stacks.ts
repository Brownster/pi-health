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

export function getStackServicesPercent(stack: StackSummary): number | null {
  if (stack.container_count === null || stack.container_count <= 0 || stack.running_count === null) {
    return null;
  }
  return Math.round((stack.running_count / stack.container_count) * 100);
}
