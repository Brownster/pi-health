import { requestApi, toNullableNumber } from "@/lib/api";

export interface UsageSummary {
  total: number | null;
  used: number | null;
  free: number | null;
  percent: number | null;
}

export interface SystemStats {
  cpuPercent: number | null;
  perCore: number[];
  memory: UsageSummary;
  disk: UsageSummary;
  disk2: UsageSummary;
  temperatureCelsius: number | null;
  networkReceived: number | null;
  networkSent: number | null;
  cpuFreqMhz: number | null;
  throttling: string | null;
  isRaspberryPi: boolean;
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

export async function fetchSystemStats(signal?: AbortSignal): Promise<SystemStats> {
  const payload = await requestApi<Record<string, unknown>>("/api/stats", {
    method: "GET",
    signal,
  });
  const network =
    payload.network_usage && typeof payload.network_usage === "object"
      ? (payload.network_usage as Record<string, unknown>)
      : {};

  const perCore = Array.isArray(payload.cpu_usage_per_core)
    ? payload.cpu_usage_per_core.map((value) => toNullableNumber(value)).filter((v): v is number => v !== null)
    : [];

  return {
    cpuPercent: toNullableNumber(payload.cpu_usage_percent),
    perCore,
    memory: normalizeUsage(payload.memory_usage),
    disk: normalizeUsage(payload.disk_usage),
    disk2: normalizeUsage(payload.disk_usage_2),
    temperatureCelsius: toNullableNumber(payload.temperature_celsius),
    networkReceived: toNullableNumber(network.bytes_recv),
    networkSent: toNullableNumber(network.bytes_sent),
    cpuFreqMhz: toNullableNumber(payload.cpu_freq_mhz),
    throttling: typeof payload.throttling === "string" ? payload.throttling : null,
    isRaspberryPi: Boolean(payload.is_raspberry_pi),
  };
}
