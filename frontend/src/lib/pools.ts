/**
 * Typed views over the storage plugin detail/status payloads for the Pools tab.
 *
 * The backend already returns everything these views need in `detail.status`
 * (PH4-001); this module keeps the parsing out of the card components.
 */
import type { PluginDetail } from "@/lib/storage-plugins";

type Details = Record<string, unknown>;

function statusDetails(detail: PluginDetail | null): Details {
  const status = (detail?.status ?? {}) as Record<string, unknown>;
  const details = status.details;
  return details && typeof details === "object" ? (details as Details) : {};
}

function num(value: unknown): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export type SnapraidState = "healthy" | "sync_required" | "error" | "unconfigured";

export interface SnapraidView {
  state: SnapraidState;
  message: string;
  dataDrives: number | null;
  parityDrives: number | null;
  lastCommand: string | null;
  lastRunAt: string | null;
  lastSummary: Record<string, number> | null;
}

export function snapraidView(detail: PluginDetail | null): SnapraidView {
  const status = (detail?.status ?? {}) as Record<string, unknown>;
  const details = statusDetails(detail);
  const rawStatus = String(status.status ?? "unconfigured");

  let state: SnapraidState;
  if (rawStatus === "unconfigured") {
    state = "unconfigured";
  } else if (details.sync_required === true || rawStatus === "degraded") {
    state = "sync_required";
  } else if (rawStatus === "error") {
    state = "error";
  } else {
    state = "healthy";
  }

  let lastSummary: Record<string, number> | null = null;
  const summaryRaw = details.last_summary;
  if (summaryRaw && typeof summaryRaw === "object") {
    const parsed: Record<string, number> = {};
    for (const [key, value] of Object.entries(summaryRaw as Record<string, unknown>)) {
      const parsedValue = num(value);
      if (parsedValue !== null) {
        parsed[key] = parsedValue;
      }
    }
    if (Object.keys(parsed).length) {
      lastSummary = parsed;
    }
  }

  return {
    state,
    message: String(status.message ?? ""),
    dataDrives: num(details.data_drives),
    parityDrives: num(details.parity_drives),
    lastCommand: details.last_command != null ? String(details.last_command) : null,
    lastRunAt: details.last_run_at != null ? String(details.last_run_at) : null,
    lastSummary,
  };
}

export interface MergerfsPoolView {
  name: string;
  mountPoint: string | null;
  mounted: boolean;
  branchCount: number;
  usedPercent: number | null;
  totalBytes: number | null;
  freeBytes: number | null;
}

export function mergerfsPools(detail: PluginDetail | null): MergerfsPoolView[] {
  const details = statusDetails(detail);
  const pools = Array.isArray(details.pools) ? (details.pools as Record<string, unknown>[]) : [];
  return pools.map((pool) => ({
    name: String(pool.name ?? "pool"),
    mountPoint: pool.mount_point != null ? String(pool.mount_point) : null,
    mounted: Boolean(pool.mounted),
    branchCount: num(pool.branches) ?? 0,
    usedPercent: num(pool.used_percent),
    totalBytes: num(pool.total_bytes),
    freeBytes: num(pool.free_bytes),
  }));
}

/** Compact relative age like "2 d ago" from an ISO timestamp. */
export function relativeAge(iso: string | null): string | null {
  if (!iso) {
    return null;
  }
  const then = Date.parse(iso);
  if (Number.isNaN(then)) {
    return null;
  }
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) {
    return "just now";
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `${minutes} m ago`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours} h ago`;
  }
  const days = Math.floor(hours / 24);
  return `${days} d ago`;
}
