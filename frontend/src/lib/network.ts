import { requestApi, toNullableString } from "@/lib/api";

export interface NetworkGroup {
  provider: string;
  provider_status: string;
  provider_health: string | null;
  members: string[];
  member_count: number;
  orphaned_members: string[];
  status: string;
}

export interface NetworkGroupsResult {
  docker_available: boolean;
  groups: NetworkGroup[];
}

export async function fetchNetworkGroups(signal?: AbortSignal): Promise<NetworkGroupsResult> {
  const payload = await requestApi<{
    docker_available?: boolean;
    groups?: Record<string, unknown>[];
  }>("/api/network-groups", { method: "GET", signal });

  const groups = Array.isArray(payload.groups)
    ? payload.groups.map((raw) => ({
        provider: String(raw.provider ?? ""),
        provider_status: String(raw.provider_status ?? "unknown"),
        provider_health: toNullableString(raw.provider_health),
        members: Array.isArray(raw.members) ? raw.members.map((m) => String(m)) : [],
        member_count: Number(raw.member_count ?? 0),
        orphaned_members: Array.isArray(raw.orphaned_members)
          ? raw.orphaned_members.map((m) => String(m))
          : [],
        status: String(raw.status ?? "ok"),
      }))
    : [];

  return { docker_available: Boolean(payload.docker_available), groups };
}

export async function recreateNetworkGroup(provider: string, signal?: AbortSignal): Promise<void> {
  const payload = await requestApi<{ status?: string; error?: string }>(
    `/api/network-groups/${encodeURIComponent(provider)}/recreate`,
    { method: "POST", signal },
  );
  if (payload.error) {
    throw new Error(payload.error);
  }
}

export interface TailscaleStatus {
  available: boolean;
  data: Record<string, unknown> | null;
}

/** Tailscale status is helper-dependent; 503/unavailable is a normal state, not an error. */
export async function fetchTailscaleStatus(signal?: AbortSignal): Promise<TailscaleStatus> {
  const response = await fetch("/api/tailscale/status", {
    method: "GET",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    return { available: false, data: null };
  }
  const data = (await response.json().catch(() => null)) as Record<string, unknown> | null;
  if (!data || data.error) {
    return { available: false, data };
  }
  return { available: true, data };
}

export async function tailscaleLogout(signal?: AbortSignal): Promise<void> {
  const payload = await requestApi<{ status?: string; error?: string }>("/api/tailscale/logout", {
    method: "POST",
    signal,
  });
  if (payload.error) {
    throw new Error(payload.error);
  }
}
