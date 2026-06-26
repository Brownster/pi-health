import { requestApi, toNullableString } from "@/lib/api";

export interface MediaPaths {
  downloads: string;
  storage: string;
  backup: string;
  config: string;
}

export const MEDIA_PATH_KEYS = ["downloads", "storage", "backup", "config"] as const;
export type MediaPathKey = (typeof MEDIA_PATH_KEYS)[number];

export async function fetchMediaPaths(signal?: AbortSignal): Promise<MediaPaths> {
  const payload = await requestApi<{ paths?: Partial<MediaPaths> }>("/api/disks/media-paths", {
    method: "GET",
    signal,
  });
  const paths = payload.paths ?? {};
  return {
    downloads: String(paths.downloads ?? ""),
    storage: String(paths.storage ?? ""),
    backup: String(paths.backup ?? ""),
    config: String(paths.config ?? ""),
  };
}

export async function saveMediaPaths(paths: MediaPaths, signal?: AbortSignal): Promise<{ warning: string | null }> {
  const payload = await requestApi<{ status?: string; startup_warning?: string; error?: string }>(
    "/api/disks/media-paths",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(paths),
      signal,
    },
  );
  if (payload.error) {
    throw new Error(payload.error);
  }
  return { warning: toNullableString(payload.startup_warning) };
}

export interface MountEntry {
  id: string;
  name: string;
  mountpoint: string | null;
  mounted: boolean;
  type: string | null;
}

export interface PluginMounts {
  pluginId: string;
  pluginName: string;
  mounts: MountEntry[];
}

function normalizeMount(raw: Record<string, unknown> | undefined): MountEntry {
  return {
    id: String(raw?.id ?? raw?.mount_id ?? raw?.name ?? ""),
    name: String(raw?.name ?? raw?.id ?? "mount"),
    mountpoint: toNullableString(raw?.mountpoint ?? raw?.target),
    mounted: Boolean(raw?.mounted ?? raw?.is_mounted),
    type: toNullableString(raw?.type ?? raw?.remote_type),
  };
}

/** Returns mounts for a plugin, or null if the plugin is not a remote-mount plugin (400/404). */
export async function fetchPluginMounts(pluginId: string, signal?: AbortSignal): Promise<MountEntry[] | null> {
  const response = await fetch(`/api/storage/mounts/${encodeURIComponent(pluginId)}`, {
    method: "GET",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal,
  });
  if (response.status === 400 || response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Mounts request failed (${response.status})`);
  }
  const payload = (await response.json()) as { mounts?: Record<string, unknown>[]; error?: string };
  if (payload.error || !Array.isArray(payload.mounts)) {
    return null;
  }
  return payload.mounts.map((mount) => normalizeMount(mount));
}

async function mountAction(path: string, method: string, signal?: AbortSignal): Promise<void> {
  const payload = await requestApi<{ status?: string; error?: string }>(path, { method, signal });
  if (payload.error) {
    throw new Error(payload.error);
  }
}

export function mountEntry(pluginId: string, mountId: string, signal?: AbortSignal): Promise<void> {
  return mountAction(
    `/api/storage/mounts/${encodeURIComponent(pluginId)}/${encodeURIComponent(mountId)}/mount`,
    "POST",
    signal,
  );
}

export function unmountEntry(pluginId: string, mountId: string, signal?: AbortSignal): Promise<void> {
  return mountAction(
    `/api/storage/mounts/${encodeURIComponent(pluginId)}/${encodeURIComponent(mountId)}/unmount`,
    "POST",
    signal,
  );
}

export function deleteMount(pluginId: string, mountId: string, signal?: AbortSignal): Promise<void> {
  return mountAction(
    `/api/storage/mounts/${encodeURIComponent(pluginId)}/${encodeURIComponent(mountId)}`,
    "DELETE",
    signal,
  );
}
