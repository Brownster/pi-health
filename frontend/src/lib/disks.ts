import { requestApi, toNullableNumber, toNullableString } from "@/lib/api";

export interface DiskPartition {
  name: string;
  path: string;
  size: string | null;
  fstype: string | null;
  mountpoint: string | null;
  uuid: string | null;
  label: string | null;
}

export interface DiskInfo {
  name: string;
  path: string;
  type: string;
  size: string | null;
  model: string | null;
  serial: string | null;
  transport: string | null;
  mountpoint: string | null;
  fstype: string | null;
  uuid: string | null;
  label: string | null;
  partitions: DiskPartition[];
}

export interface DiskInventory {
  disks: DiskInfo[];
  helper_available: boolean;
}

export interface HelperStatus {
  available: boolean;
  socket_path: string | null;
}

export interface SmartHealth {
  device: string;
  model: string | null;
  serial: string | null;
  drive_type: string | null;
  smart_available: boolean;
  smart_enabled: boolean;
  health_status: string;
  temperature_c: number | null;
  power_on_hours: number | null;
  reallocated_sectors: number | null;
  pending_sectors: number | null;
  uncorrectable_errors: number | null;
  percentage_used: number | null;
  available_spare: number | null;
  media_errors: number | null;
  error_message: string | null;
}

function normalizePartition(raw: Record<string, unknown> | undefined): DiskPartition {
  return {
    name: String(raw?.name ?? ""),
    path: String(raw?.path ?? ""),
    size: toNullableString(raw?.size),
    fstype: toNullableString(raw?.fstype),
    mountpoint: toNullableString(raw?.mountpoint),
    uuid: toNullableString(raw?.uuid),
    label: toNullableString(raw?.label),
  };
}

function normalizeDisk(raw: Record<string, unknown> | undefined): DiskInfo {
  const partitions = Array.isArray(raw?.partitions) ? (raw?.partitions as Record<string, unknown>[]) : [];
  return {
    name: String(raw?.name ?? ""),
    path: String(raw?.path ?? ""),
    type: String(raw?.type ?? ""),
    size: toNullableString(raw?.size),
    model: toNullableString(raw?.model),
    serial: toNullableString(raw?.serial),
    transport: toNullableString(raw?.transport),
    mountpoint: toNullableString(raw?.mountpoint),
    fstype: toNullableString(raw?.fstype),
    uuid: toNullableString(raw?.uuid),
    label: toNullableString(raw?.label),
    partitions: partitions.map((part) => normalizePartition(part)),
  };
}

function normalizeSmart(raw: Record<string, unknown> | undefined, fallbackDevice = ""): SmartHealth {
  return {
    device: String(raw?.device ?? fallbackDevice),
    model: toNullableString(raw?.model),
    serial: toNullableString(raw?.serial),
    drive_type: toNullableString(raw?.drive_type),
    smart_available: Boolean(raw?.smart_available),
    smart_enabled: Boolean(raw?.smart_enabled),
    health_status: String(raw?.health_status ?? "unknown"),
    temperature_c: toNullableNumber(raw?.temperature_c),
    power_on_hours: toNullableNumber(raw?.power_on_hours),
    reallocated_sectors: toNullableNumber(raw?.reallocated_sectors),
    pending_sectors: toNullableNumber(raw?.pending_sectors),
    uncorrectable_errors: toNullableNumber(raw?.uncorrectable_errors),
    percentage_used: toNullableNumber(raw?.percentage_used),
    available_spare: toNullableNumber(raw?.available_spare),
    media_errors: toNullableNumber(raw?.media_errors),
    error_message: toNullableString(raw?.error_message),
  };
}

export async function fetchDiskInventory(signal?: AbortSignal): Promise<DiskInventory> {
  const payload = await requestApi<{ disks?: Record<string, unknown>[]; helper_available?: boolean; error?: string }>(
    "/api/disks",
    { method: "GET", signal },
  );
  if (payload.error) {
    throw new Error(payload.error);
  }
  return {
    disks: Array.isArray(payload.disks) ? payload.disks.map((disk) => normalizeDisk(disk)) : [],
    helper_available: Boolean(payload.helper_available),
  };
}

export async function fetchHelperStatus(signal?: AbortSignal): Promise<HelperStatus> {
  const payload = await requestApi<{ available?: boolean; socket_path?: string }>(
    "/api/disks/helper-status",
    { method: "GET", signal },
  );
  return {
    available: Boolean(payload.available),
    socket_path: toNullableString(payload.socket_path),
  };
}

/** SMART summary keyed by device path; supplementary, so callers may treat failure as empty. */
export async function fetchSmartSummary(signal?: AbortSignal): Promise<Record<string, SmartHealth>> {
  const payload = await requestApi<{
    disks?: Array<{ device?: string; data?: Record<string, unknown> }>;
    error?: string;
  }>("/api/disks/smart", { method: "GET", signal });

  if (payload.error || !Array.isArray(payload.disks)) {
    return {};
  }

  return payload.disks.reduce<Record<string, SmartHealth>>((acc, entry) => {
    const device = String(entry.device ?? "");
    if (device) {
      acc[device] = normalizeSmart(entry.data, device);
    }
    return acc;
  }, {});
}

export async function fetchDiskSmart(deviceName: string, signal?: AbortSignal): Promise<SmartHealth> {
  const payload = await requestApi<Record<string, unknown> & { error?: string }>(
    `/api/disks/${encodeURIComponent(deviceName)}/smart`,
    { method: "GET", signal },
  );
  if (payload.error) {
    throw new Error(String(payload.error));
  }
  return normalizeSmart(payload, deviceName);
}

export interface SuggestedMount {
  device: string;
  uuid: string;
  size: string | null;
  fstype: string;
  label: string | null;
  suggested_mount: string;
  reason: string;
}

export async function fetchSuggestedMounts(signal?: AbortSignal): Promise<SuggestedMount[]> {
  const payload = await requestApi<{ suggestions?: Record<string, unknown>[]; error?: string }>(
    "/api/disks/suggested-mounts",
    { method: "GET", signal },
  );
  if (payload.error || !Array.isArray(payload.suggestions)) {
    return [];
  }
  return payload.suggestions
    .map((raw) => ({
      device: String(raw.device ?? ""),
      uuid: String(raw.uuid ?? ""),
      size: toNullableString(raw.size),
      fstype: String(raw.fstype ?? ""),
      label: toNullableString(raw.label),
      suggested_mount: String(raw.suggested_mount ?? ""),
      reason: String(raw.reason ?? ""),
    }))
    .filter((item) => item.uuid && item.fstype && item.suggested_mount);
}

export interface MountRequest {
  uuid: string;
  mountpoint: string;
  fstype: string;
  add_to_fstab?: boolean;
}

export async function mountDisk(request: MountRequest, signal?: AbortSignal): Promise<void> {
  const payload = await requestApi<{ status?: string; error?: string }>("/api/disks/mount", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      uuid: request.uuid,
      mountpoint: request.mountpoint,
      fstype: request.fstype,
      add_to_fstab: request.add_to_fstab ?? true,
    }),
    signal,
  });
  if (payload.error) {
    throw new Error(payload.error);
  }
}

export async function unmountDisk(
  mountpoint: string,
  removeFromFstab = false,
  signal?: AbortSignal,
): Promise<{ warning: string | null }> {
  const payload = await requestApi<{ status?: string; warning?: string; error?: string }>(
    "/api/disks/unmount",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mountpoint, remove_from_fstab: removeFromFstab }),
      signal,
    },
  );
  if (payload.error) {
    throw new Error(payload.error);
  }
  return { warning: toNullableString(payload.warning) };
}

export type SmartTestType = "short" | "long" | "conveyance";

export async function runSmartTest(
  deviceName: string,
  testType: SmartTestType,
  signal?: AbortSignal,
): Promise<string> {
  const payload = await requestApi<{ status?: string; message?: string; error?: string }>(
    `/api/disks/${encodeURIComponent(deviceName)}/smart-test`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ test_type: testType }),
      signal,
    },
  );
  if (payload.error) {
    throw new Error(payload.error);
  }
  return payload.message || `${testType} self-test started`;
}
