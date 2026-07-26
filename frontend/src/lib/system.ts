import { requestApi, toNullableNumber } from "@/lib/api";

export interface UsageSummary {
  total: number | null;
  used: number | null;
  free: number | null;
  percent: number | null;
}

export interface MetricWarning {
  code: string;
  metric: string;
  source: string;
  message: string;
}

export interface LoadAverage {
  one: number | null;
  five: number | null;
  fifteen: number | null;
  cpuCount: number | null;
  perCore: number | null;
}

export interface SystemStats {
  cpuPercent: number | null;
  perCore: number[];
  memory: UsageSummary;
  swap: UsageSummary;
  disk: UsageSummary;
  disk2: UsageSummary;
  loadAverage: LoadAverage | null;
  uptimeSeconds: number | null;
  temperatureCelsius: number | null;
  networkReceived: number | null;
  networkSent: number | null;
  cpuFreqMhz: number | null;
  throttling: string | null;
  isRaspberryPi: boolean;
  warnings: MetricWarning[];
}

function normalizeLoadAverage(value: unknown): LoadAverage | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const load = value as Record<string, unknown>;
  return {
    one: toNullableNumber(load.one),
    five: toNullableNumber(load.five),
    fifteen: toNullableNumber(load.fifteen),
    cpuCount: toNullableNumber(load.cpu_count),
    perCore: toNullableNumber(load.per_core),
  };
}

function normalizeUsage(value: unknown): UsageSummary {
  const usage = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    total: toNullableNumber(usage.total),
    used: toNullableNumber(usage.used),
    free: toNullableNumber(usage.free),
    percent: toNullableNumber(usage.percent),
  };
}

function normalizeWarnings(value: unknown): MetricWarning[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((warning): warning is Record<string, unknown> => Boolean(warning && typeof warning === "object"))
    .map((warning) => ({
      code: String(warning.code ?? "unknown"),
      metric: String(warning.metric ?? "unknown"),
      source: String(warning.source ?? "unknown"),
      message: String(warning.message ?? "Metric unavailable"),
    }));
}

export async function fetchSystemStats(signal?: AbortSignal): Promise<SystemStats> {
  const payload = await requestApi<Record<string, unknown>>("/api/stats", {
    method: "GET",
    signal,
  });
  const network =
    payload.network_usage && typeof payload.network_usage === "object"
      ? (payload.network_usage as Record<string, unknown>)
      : {};

  // /api/stats reports each core as {core, usage_percent}; older builds sent bare numbers.
  const perCore = Array.isArray(payload.cpu_usage_per_core)
    ? payload.cpu_usage_per_core
        .map((value) =>
          value && typeof value === "object"
            ? toNullableNumber((value as Record<string, unknown>).usage_percent)
            : toNullableNumber(value),
        )
        .filter((value): value is number => value !== null)
    : [];

  return {
    cpuPercent: toNullableNumber(payload.cpu_usage_percent),
    perCore,
    memory: normalizeUsage(payload.memory_usage),
    swap: normalizeUsage(payload.swap_usage),
    disk: normalizeUsage(payload.disk_usage),
    disk2: normalizeUsage(payload.disk_usage_2),
    loadAverage: normalizeLoadAverage(payload.load_average),
    uptimeSeconds: toNullableNumber(payload.uptime_seconds),
    temperatureCelsius: toNullableNumber(payload.temperature_celsius),
    networkReceived: toNullableNumber(network.bytes_recv),
    networkSent: toNullableNumber(network.bytes_sent),
    cpuFreqMhz: toNullableNumber(payload.cpu_freq_mhz),
    throttling: typeof payload.throttling === "string" ? payload.throttling : null,
    isRaspberryPi: Boolean(payload.is_raspberry_pi),
    warnings: normalizeWarnings(payload.warnings),
  };
}
