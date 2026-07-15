import { requestApi } from "@/lib/api";

export type OverviewHealthState = "healthy" | "attention" | "critical" | "unknown";
export type OverviewSeverity = "critical" | "attention" | "unknown";

export interface OverviewIssue {
  code: string;
  severity: OverviewSeverity;
  label: string;
  detail: string;
  path: string;
}

export interface OverviewMetrics {
  cpu_percent: number | null;
  memory_percent: number | null;
  memory_used: number | null;
  memory_total: number | null;
  temperature_celsius: number | null;
  disk_percent: number | null;
  disk_used: number | null;
  disk_total: number | null;
}

export interface OverviewContainerCounts {
  total: number;
  running: number;
  unhealthy: number;
  stopped: number;
}

export interface OverviewStackCounts {
  total: number;
  healthy: number;
  partial: number;
  down: number;
  unknown: number;
}

export interface OverviewAlertRecord {
  event: "incident" | "recovery";
  key: string;
  kind: string;
  severity: string;
  summary: string;
  at: string;
}

export interface OverviewApplication {
  id: string;
  name: string;
  status: string;
  image: string;
  port: number | null;
  web_url: string | null;
  web_scheme: "http" | "https" | null;
}

export interface OverviewWarning {
  code: string;
  source: string;
  message: string;
}

export interface OverviewSnapshot {
  health: {
    state: OverviewHealthState;
    issues: OverviewIssue[];
  };
  metrics: OverviewMetrics;
  workloads: {
    containers: OverviewContainerCounts;
    stacks: OverviewStackCounts;
  };
  alerts: {
    active: OverviewAlertRecord[];
    recent_recoveries: OverviewAlertRecord[];
  };
  applications: OverviewApplication[];
  warnings: OverviewWarning[];
  collected_at: string;
}

export async function fetchOverview(signal?: AbortSignal): Promise<OverviewSnapshot> {
  return requestApi<OverviewSnapshot>("/api/overview", { method: "GET", signal });
}

export function getOverviewApplicationUrl(
  application: OverviewApplication,
  hostname = typeof window === "undefined" ? null : window.location.hostname,
): string | null {
  if (application.web_url) {
    try {
      const explicitUrl = new URL(application.web_url);
      if (
        (explicitUrl.protocol === "http:" || explicitUrl.protocol === "https:") &&
        !explicitUrl.username &&
        !explicitUrl.password
      ) {
        return explicitUrl.href;
      }
    } catch {
      // Invalid application metadata is intentionally treated as unavailable.
    }
  }

  if (!application.port || !hostname) {
    return null;
  }
  const scheme = application.web_scheme ?? "http";
  const formattedHostname = hostname.includes(":") && !hostname.startsWith("[")
    ? `[${hostname}]`
    : hostname;
  return `${scheme}://${formattedHostname}:${application.port}`;
}
