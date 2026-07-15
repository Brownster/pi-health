import { requestApi } from "@/lib/api";

export type MetricHistoryRange = "24h" | "7d" | "30d";
export type HistoricalMetric =
  | "cpu_percent"
  | "memory_percent"
  | "temperature_celsius"
  | "disk_percent";

export interface MetricHistoryPoint {
  at: string;
  cpu_percent: number | null;
  memory_percent: number | null;
  temperature_celsius: number | null;
  disk_percent: number | null;
}

export interface MetricHistorySummary {
  current: number | null;
  min: number | null;
  average: number | null;
  max: number | null;
}

export interface MetricHistoryResponse {
  range: MetricHistoryRange;
  from: string;
  to: string;
  bucket_seconds: number;
  points: MetricHistoryPoint[];
  summary: Record<HistoricalMetric, MetricHistorySummary>;
}

export async function fetchMetricHistory(
  range: MetricHistoryRange,
  signal?: AbortSignal,
): Promise<MetricHistoryResponse> {
  return requestApi<MetricHistoryResponse>(
    `/api/system/history?range=${encodeURIComponent(range)}`,
    { method: "GET", signal },
  );
}
