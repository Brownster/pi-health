import { requestApi, toNullableString } from "@/lib/api";

export interface ShareEntry {
  name: string;
  path: string | null;
  enabled: boolean;
}

export interface PluginShares {
  pluginId: string;
  pluginName: string;
  serviceRunning: boolean;
  status: string | null;
  message: string | null;
  shares: ShareEntry[];
}

function normalizeShare(raw: Record<string, unknown> | undefined): ShareEntry {
  return {
    name: String(raw?.name ?? ""),
    path: toNullableString(raw?.path),
    // Shares default to enabled unless explicitly disabled.
    enabled: raw?.enabled === undefined ? true : Boolean(raw?.enabled),
  };
}

export async function fetchShares(
  pluginId: string,
  pluginName: string,
  signal?: AbortSignal,
): Promise<PluginShares> {
  const payload = await requestApi<{
    shares?: Record<string, unknown>[];
    service_running?: boolean;
    status?: string;
    message?: string;
    error?: string;
  }>(`/api/storage/shares/${encodeURIComponent(pluginId)}`, { method: "GET", signal });

  if (payload.error) {
    throw new Error(payload.error);
  }
  if (!Array.isArray(payload.shares)) {
    throw new Error("Share list response is invalid");
  }

  return {
    pluginId,
    pluginName,
    serviceRunning: Boolean(payload.service_running),
    status: toNullableString(payload.status),
    message: toNullableString(payload.message),
    shares: payload.shares.map((share) => normalizeShare(share)),
  };
}

async function shareAction(path: string, method: string, signal?: AbortSignal): Promise<void> {
  const payload = await requestApi<{ status?: string; error?: string }>(path, { method, signal });
  if (payload.error) {
    throw new Error(payload.error);
  }
}

export function toggleShare(pluginId: string, shareName: string, signal?: AbortSignal): Promise<void> {
  return shareAction(
    `/api/storage/shares/${encodeURIComponent(pluginId)}/${encodeURIComponent(shareName)}/toggle`,
    "POST",
    signal,
  );
}

export function deleteShare(pluginId: string, shareName: string, signal?: AbortSignal): Promise<void> {
  return shareAction(
    `/api/storage/shares/${encodeURIComponent(pluginId)}/${encodeURIComponent(shareName)}`,
    "DELETE",
    signal,
  );
}

async function shareConfigRequest(
  path: string,
  method: string,
  share: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<void> {
  const payload = await requestApi<{ status?: string; error?: string }>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(share),
    signal,
  });
  if (payload.error) {
    throw new Error(payload.error);
  }
}

export function addShare(pluginId: string, share: Record<string, unknown>, signal?: AbortSignal): Promise<void> {
  return shareConfigRequest(`/api/storage/shares/${encodeURIComponent(pluginId)}`, "POST", share, signal);
}

export function updateShare(
  pluginId: string,
  shareName: string,
  share: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<void> {
  return shareConfigRequest(
    `/api/storage/shares/${encodeURIComponent(pluginId)}/${encodeURIComponent(shareName)}`,
    "PUT",
    share,
    signal,
  );
}
