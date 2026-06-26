import { requestApi, toNullableString } from "@/lib/api";

export interface StoragePlugin {
  id: string;
  name: string;
  description: string;
  version: string;
  installed: boolean;
  enabled: boolean;
  configured: boolean;
  status: string;
  status_message: string;
  category: string;
  type: string;
}

export interface PluginCommand {
  id: string;
  label: string;
  params: string[];
}

export interface PluginDetail {
  id: string;
  name: string;
  description: string;
  installed: boolean;
  status: Record<string, unknown>;
  commands: PluginCommand[];
}

export interface PluginRecovery {
  supported: boolean;
  data: Record<string, unknown> | null;
}

export interface PluginCommandEvent {
  type: string;
  line?: string;
  success?: boolean;
  message?: string;
  error?: string;
}

function normalizePlugin(raw: Record<string, unknown> | undefined): StoragePlugin {
  return {
    id: String(raw?.id ?? ""),
    name: String(raw?.name ?? raw?.id ?? "unknown"),
    description: String(raw?.description ?? ""),
    version: String(raw?.version ?? ""),
    installed: Boolean(raw?.installed),
    enabled: Boolean(raw?.enabled),
    configured: Boolean(raw?.configured),
    status: String(raw?.status ?? "unknown"),
    status_message: String(raw?.status_message ?? ""),
    category: String(raw?.category ?? "storage"),
    type: String(raw?.type ?? "builtin"),
  };
}

export async function fetchPlugins(signal?: AbortSignal): Promise<StoragePlugin[]> {
  const payload = await requestApi<{ plugins?: Record<string, unknown>[] }>("/api/storage/plugins", {
    method: "GET",
    signal,
  });
  return Array.isArray(payload.plugins) ? payload.plugins.map((item) => normalizePlugin(item)) : [];
}

export async function fetchPluginDetail(pluginId: string, signal?: AbortSignal): Promise<PluginDetail> {
  const payload = await requestApi<Record<string, unknown> & { error?: string }>(
    `/api/storage/plugins/${encodeURIComponent(pluginId)}`,
    { method: "GET", signal },
  );
  if (payload.error) {
    throw new Error(String(payload.error));
  }
  const commands = Array.isArray(payload.commands) ? (payload.commands as Record<string, unknown>[]) : [];
  return {
    id: String(payload.id ?? pluginId),
    name: String(payload.name ?? pluginId),
    description: String(payload.description ?? ""),
    installed: Boolean(payload.installed),
    status: (payload.status as Record<string, unknown>) ?? {},
    commands: commands.map((cmd) => ({
      id: String(cmd.id ?? ""),
      label: String(cmd.label ?? cmd.id ?? ""),
      params: Array.isArray(cmd.params) ? cmd.params.map((p) => String(p)) : [],
    })),
  };
}

export async function togglePlugin(pluginId: string, enabled: boolean, signal?: AbortSignal): Promise<void> {
  const payload = await requestApi<{ status?: string; error?: string }>(
    `/api/storage/plugins/${encodeURIComponent(pluginId)}/toggle`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
      signal,
    },
  );
  if (payload.error) {
    throw new Error(payload.error);
  }
}

export async function removePlugin(pluginId: string, signal?: AbortSignal): Promise<void> {
  const payload = await requestApi<{ status?: string; error?: string }>(
    `/api/storage/plugins/${encodeURIComponent(pluginId)}/remove`,
    { method: "DELETE", signal },
  );
  if (payload.error) {
    throw new Error(payload.error);
  }
}

export async function fetchPluginRecovery(pluginId: string, signal?: AbortSignal): Promise<PluginRecovery> {
  const response = await fetch(`/api/storage/plugins/${encodeURIComponent(pluginId)}/recovery`, {
    method: "GET",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal,
  });
  // 404 means recovery is not supported by this plugin — that's expected, not an error.
  if (response.status === 404) {
    return { supported: false, data: null };
  }
  if (!response.ok) {
    throw new Error(`Recovery request failed (${response.status})`);
  }
  return { supported: true, data: (await response.json()) as Record<string, unknown> };
}

export async function fetchPluginLatestLog(pluginId: string, signal?: AbortSignal): Promise<string | null> {
  const response = await fetch(`/api/storage/plugins/${encodeURIComponent(pluginId)}/logs/latest`, {
    method: "GET",
    credentials: "same-origin",
    signal,
  });
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Log request failed (${response.status})`);
  }
  return await response.text();
}

/**
 * Run a plugin command. The endpoint streams SSE over POST, so EventSource (GET-only)
 * cannot be used — consume the body with a ReadableStream reader and parse `data:` frames.
 */
export async function streamPluginCommand(
  pluginId: string,
  commandId: string,
  params: Record<string, unknown>,
  onEvent: (event: PluginCommandEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(
    `/api/storage/plugins/${encodeURIComponent(pluginId)}/commands/${encodeURIComponent(commandId)}`,
    {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(params ?? {}),
      signal,
    },
  );

  if (!response.ok || !response.body) {
    throw new Error(`Command failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    let separator = buffer.indexOf("\n\n");
    while (separator !== -1) {
      const frame = buffer.slice(0, separator);
      buffer = buffer.slice(separator + 2);
      const dataLine = frame.split("\n").find((line) => line.startsWith("data:"));
      if (dataLine) {
        try {
          onEvent(JSON.parse(dataLine.slice(5).trim()) as PluginCommandEvent);
        } catch {
          // ignore malformed frame
        }
      }
      separator = buffer.indexOf("\n\n");
    }
  }
}

export function isPoolPlugin(plugin: StoragePlugin): boolean {
  // No explicit capability flag in the list payload; treat the parity/pool plugins as
  // pool-capable (documented heuristic; revisit if the API gains a capability field).
  return plugin.category.toLowerCase().includes("pool") || ["mergerfs", "snapraid"].includes(plugin.id);
}

export { toNullableString };
