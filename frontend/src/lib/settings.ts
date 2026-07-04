import { requestApi, toNullableString } from "@/lib/api";
import { createOperation, streamOperation, type OperationEvent } from "@/lib/operations";

// --- Pi-Health self-update ---------------------------------------------------

export interface PiHealthUpdateConfig {
  repo_path: string;
  service_name: string;
}

export async function fetchPiHealthUpdateConfig(signal?: AbortSignal): Promise<PiHealthUpdateConfig> {
  const payload = await requestApi<Partial<PiHealthUpdateConfig>>("/api/pihealth/update/config", {
    method: "GET",
    signal,
  });
  return {
    repo_path: String(payload.repo_path ?? ""),
    service_name: String(payload.service_name ?? ""),
  };
}

export async function savePiHealthUpdateConfig(config: PiHealthUpdateConfig, signal?: AbortSignal): Promise<void> {
  const payload = await requestApi<{ status?: string; error?: string }>("/api/pihealth/update/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
    signal,
  });
  if (payload.error) {
    throw new Error(payload.error);
  }
}

export type { OperationEvent };

/**
 * Start a streamed self-update and forward each progress event to `onEvent`.
 *
 * Resolves once the operation stream completes. The terminal event is either an
 * error, an "already up to date" done, or a `restarting` done — in the last case
 * the service is going down, so callers should then poll {@link waitForServiceRecovery}.
 */
export async function runPiHealthUpdate(
  onEvent: (event: OperationEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const { stream_url } = await createOperation("/api/pihealth/update", {}, signal);
  await streamOperation(stream_url, onEvent, signal);
}

/**
 * Poll `/api/health` until the service answers again after a restart.
 *
 * Any HTTP response (even 401) means the server is back; a rejected fetch means
 * it is still restarting. Resolves `true` on recovery, `false` if it times out.
 */
export async function waitForServiceRecovery(
  { timeoutMs = 120_000, intervalMs = 2_000 }: { timeoutMs?: number; intervalMs?: number } = {},
  signal?: AbortSignal,
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (signal?.aborted) {
      return false;
    }
    try {
      const response = await fetch("/api/health", {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        signal,
      });
      if (response.status > 0) {
        return true;
      }
    } catch {
      // Connection refused / reset while the service restarts — keep polling.
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  return false;
}

/**
 * After recovery, report whether the browser session survived the restart.
 *
 * These installs do not persist `SECRET_KEY`, so a restart usually invalidates
 * the session and the user must log in again.
 */
export async function isStillAuthenticated(signal?: AbortSignal): Promise<boolean> {
  try {
    const payload = await requestApi<{ authenticated?: boolean }>("/api/auth/check", {
      method: "GET",
      signal,
    });
    return Boolean(payload.authenticated);
  } catch {
    return false;
  }
}

// --- Backups -----------------------------------------------------------------

export interface BackupConfig {
  enabled: boolean;
  schedule_preset: string;
  retention_count: number | null;
  dest_dir: string;
}

export interface BackupStatus {
  enabled: boolean;
  next_run: string | null;
  backup_running: boolean;
  last_run: string | null;
  last_run_result: string | null;
}

export async function fetchBackupConfig(signal?: AbortSignal): Promise<BackupConfig> {
  const payload = await requestApi<Record<string, unknown>>("/api/backups/config", { method: "GET", signal });
  return {
    enabled: Boolean(payload.enabled),
    schedule_preset: String(payload.schedule_preset ?? "daily"),
    retention_count: payload.retention_count === undefined ? null : Number(payload.retention_count),
    dest_dir: String(payload.dest_dir ?? ""),
  };
}

export async function saveBackupConfig(config: Partial<BackupConfig>, signal?: AbortSignal): Promise<void> {
  const payload = await requestApi<{ error?: string }>("/api/backups/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
    signal,
  });
  if (payload.error) {
    throw new Error(payload.error);
  }
}

export async function fetchBackupStatus(signal?: AbortSignal): Promise<BackupStatus> {
  const payload = await requestApi<Record<string, unknown>>("/api/backups/status", { method: "GET", signal });
  return {
    enabled: Boolean(payload.enabled),
    next_run: toNullableString(payload.next_run),
    backup_running: Boolean(payload.backup_running),
    last_run: toNullableString(payload.last_run),
    last_run_result: toNullableString(payload.last_run_result),
  };
}

export async function runBackup(signal?: AbortSignal): Promise<void> {
  const payload = await requestApi<{ status?: string; error?: string }>("/api/backups/run", { method: "POST", signal });
  if (payload.error) {
    throw new Error(payload.error);
  }
}

export async function fetchBackupList(signal?: AbortSignal): Promise<string[]> {
  const payload = await requestApi<{ backups?: unknown[] }>("/api/backups/list", { method: "GET", signal });
  return Array.isArray(payload.backups) ? payload.backups.map((item) => String(item)).filter(Boolean) : [];
}

export async function restoreBackup(archiveName: string, signal?: AbortSignal): Promise<void> {
  const payload = await requestApi<{ status?: string; error?: string }>("/api/backups/restore", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ archive_name: archiveName }),
    signal,
  });
  if (payload.error) {
    throw new Error(payload.error);
  }
}

// --- Auto-update -------------------------------------------------------------

export interface AutoUpdateConfig {
  enabled: boolean;
  schedule_preset: string;
  notify_on_update: boolean;
}

export async function fetchAutoUpdateConfig(signal?: AbortSignal): Promise<AutoUpdateConfig> {
  const payload = await requestApi<Record<string, unknown>>("/api/auto-update/config", { method: "GET", signal });
  return {
    enabled: Boolean(payload.enabled),
    schedule_preset: String(payload.schedule_preset ?? "daily_4am"),
    notify_on_update: Boolean(payload.notify_on_update),
  };
}

export async function saveAutoUpdateConfig(config: Partial<AutoUpdateConfig>, signal?: AbortSignal): Promise<void> {
  const payload = await requestApi<{ error?: string }>("/api/auto-update/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
    signal,
  });
  if (payload.error) {
    throw new Error(payload.error);
  }
}

export async function runAutoUpdateNow(signal?: AbortSignal): Promise<void> {
  const payload = await requestApi<{ status?: string; error?: string }>("/api/auto-update/run-now", {
    method: "POST",
    signal,
  });
  if (payload.error) {
    throw new Error(payload.error);
  }
}
