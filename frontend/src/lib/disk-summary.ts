export type DiskSummarySourceState = "available" | "degraded" | "unavailable" | "not_checked";

export interface DiskProviderAssignment {
  provider_id: string;
  capability_id: string;
  role: string;
  resource_id: string;
  resource_name: string;
  href: string;
  device_path: string;
}
export interface DiskSummaryDevice {
  name: string;
  path: string;
  health: "healthy" | "warning" | "failing" | "unknown";
  temperature_c: number | null;
  mounted: boolean;
  mounted_capacity: {
    mounted_total_bytes: number;
    mounted_used_bytes: number;
    mounted_available_bytes: number;
  };
  assignments: DiskProviderAssignment[];
}

export interface DiskSummary {
  state: "healthy" | "attention" | "unavailable";
  counts: {
    total: number;
    healthy: number;
    warning: number;
    failing: number;
    unknown: number;
    mounted: number;
    unmounted: number;
    assigned: number | null;
    unassigned: number | null;
    unused: number | null;
  };
  capacity: {
    mounted_total_bytes: number;
    mounted_used_bytes: number;
    mounted_available_bytes: number;
    mounted_percent: number | null;
  };
  sources: {
    inventory: DiskSummarySourceState;
    smart: DiskSummarySourceState;
    assignments: DiskSummarySourceState;
  };
  devices: DiskSummaryDevice[];
  warnings: Array<{ code: string; source: string; message: string }>;
  collected_at: string;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function number(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

function sourceState(value: unknown): DiskSummarySourceState {
  return value === "available" || value === "degraded" || value === "not_checked"
    ? value
    : "unavailable";
}

export function normalizeDiskSummary(value: unknown): DiskSummary {
  const root = record(value);
  const counts = record(root.counts);
  const capacity = record(root.capacity);
  const sources = record(root.sources);
  const state = root.state === "healthy" || root.state === "attention" ? root.state : "unavailable";
  const devices = Array.isArray(root.devices) ? root.devices.slice(0, 128) : [];
  const warnings = Array.isArray(root.warnings) ? root.warnings.slice(0, 20) : [];

  return {
    state,
    counts: {
      total: number(counts.total),
      healthy: number(counts.healthy),
      warning: number(counts.warning),
      failing: number(counts.failing),
      unknown: number(counts.unknown),
      mounted: number(counts.mounted),
      unmounted: number(counts.unmounted),
      assigned: nullableNumber(counts.assigned),
      unassigned: nullableNumber(counts.unassigned),
      unused: nullableNumber(counts.unused),
    },
    capacity: {
      mounted_total_bytes: number(capacity.mounted_total_bytes),
      mounted_used_bytes: number(capacity.mounted_used_bytes),
      mounted_available_bytes: number(capacity.mounted_available_bytes),
      mounted_percent: nullableNumber(capacity.mounted_percent),
    },
    sources: {
      inventory: sourceState(sources.inventory),
      smart: sourceState(sources.smart),
      assignments: sourceState(sources.assignments),
    },
    devices: devices.map((item) => {
      const device = record(item);
      const mountedCapacity = record(device.mounted_capacity);
      const health =
        device.health === "healthy" || device.health === "warning" || device.health === "failing"
          ? device.health
          : "unknown";
      const assignments = Array.isArray(device.assignments) ? device.assignments.slice(0, 256) : [];
      return {
        name: text(device.name),
        path: text(device.path),
        health,
        temperature_c: nullableNumber(device.temperature_c),
        mounted: device.mounted === true,
        mounted_capacity: {
          mounted_total_bytes: number(mountedCapacity.mounted_total_bytes),
          mounted_used_bytes: number(mountedCapacity.mounted_used_bytes),
          mounted_available_bytes: number(mountedCapacity.mounted_available_bytes),
        },
        assignments: assignments.map((item) => {
          const assignment = record(item);
          return {
            provider_id: text(assignment.provider_id),
            capability_id: text(assignment.capability_id),
            role: text(assignment.role),
            resource_id: text(assignment.resource_id),
            resource_name: text(assignment.resource_name),
            href: text(assignment.href),
            device_path: text(assignment.device_path),
          };
        }),
      };
    }),
    warnings: warnings.map((item) => {
      const warning = record(item);
      return {
        code: text(warning.code),
        source: text(warning.source),
        message: text(warning.message),
      };
    }),
    collected_at: text(root.collected_at),
  };
}

interface SmartHealthSummary {
  health_status?: unknown;
  temperature_c?: unknown;
}

export function mergeDiskSummaryHealth(
  summary: DiskSummary,
  smartByPath: Record<string, SmartHealthSummary>,
): DiskSummary {
  if (!Object.keys(smartByPath).length) return summary;

  const devices = summary.devices.map((device) => {
    const smart = smartByPath[device.path];
    if (!smart) return device;
    const health: DiskSummaryDevice["health"] =
      smart.health_status === "healthy" ||
      smart.health_status === "warning" ||
      smart.health_status === "failing"
        ? smart.health_status
        : "unknown";
    return {
      ...device,
      health,
      temperature_c: nullableNumber(smart.temperature_c),
    };
  });
  const healthCounts = { healthy: 0, warning: 0, failing: 0, unknown: 0 };
  devices.forEach((device) => {
    healthCounts[device.health] += 1;
  });
  const hasAttention =
    summary.warnings.length > 0 ||
    healthCounts.warning > 0 ||
    healthCounts.failing > 0 ||
    healthCounts.unknown > 0;

  return {
    ...summary,
    state: devices.length > 0 && !hasAttention ? "healthy" : "attention",
    counts: { ...summary.counts, ...healthCounts },
    sources: { ...summary.sources, smart: "available" },
    devices,
  };
}
