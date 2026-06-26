import { requestApi, toNullableString } from "@/lib/api";

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

export async function triggerPiHealthUpdate(signal?: AbortSignal): Promise<string> {
  const payload = await requestApi<{ status?: string; error?: string }>("/api/pihealth/update", {
    method: "POST",
    signal,
  });
  if (payload.error) {
    throw new Error(payload.error);
  }
  return payload.status || "updating";
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
