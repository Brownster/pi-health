import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw, TriangleAlert } from "lucide-react";

import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MetricBar } from "@/components/ui/metric-bar";
import { PageHeader } from "@/components/ui/page-header";
import { type SystemStats, type UsageSummary, fetchSystemStats } from "@/lib/system";
import { formatBytes, formatClockTime, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 10_000;

type MetricTone = "primary" | "success" | "warning" | "danger" | "info";

function getMetricTone(percent: number | null): MetricTone {
  if (percent === null) {
    return "info";
  }
  if (percent < 50) {
    return "success";
  }
  if (percent < 80) {
    return "warning";
  }
  return "danger";
}

function getToneTextClass(tone: MetricTone): string {
  return {
    primary: "text-primary",
    success: "text-success",
    warning: "text-warning",
    danger: "text-danger",
    info: "text-info",
  }[tone];
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : "Unable to load system metrics";
}

function MetricCard({
  label,
  value,
  percent,
  detail,
  tone,
}: {
  label: string;
  value: string;
  percent: number | null;
  detail?: string;
  tone?: MetricTone;
}) {
  const resolvedTone = tone ?? getMetricTone(percent);
  return (
    <Card>
      <CardContent className="p-4">
        <p className="font-mono text-[11px] uppercase tracking-[0.1em] text-muted-foreground">{label}</p>
        <div className="mt-1 flex min-h-8 items-baseline justify-between gap-3">
          <p className={cn("font-mono text-xl font-medium", getToneTextClass(resolvedTone))}>{value}</p>
          {detail ? <p className="truncate font-mono text-[10px] text-dim">{detail}</p> : null}
        </div>
        <MetricBar className="mt-2" label={`${label} ${value}`} tone={resolvedTone} value={percent} />
      </CardContent>
    </Card>
  );
}

function usageDetail(usage: UsageSummary): string {
  if (usage.used === null || usage.total === null) {
    return "";
  }
  return `${formatBytes(usage.used)} / ${formatBytes(usage.total)}`;
}

export function SystemPage() {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState("Never");
  const isMountedRef = useRef(true);

  const loadStats = useCallback(async (reason: "initial" | "manual" | "poll") => {
    if (reason === "initial") {
      setIsLoading(true);
    }
    if (reason === "manual") {
      setIsRefreshing(true);
    }
    try {
      const next = await fetchSystemStats();
      if (!isMountedRef.current) {
        return;
      }
      setStats(next);
      setError(null);
      setLastUpdated(formatClockTime(new Date()));
    } catch (caughtError) {
      if (isMountedRef.current) {
        setError(getErrorMessage(caughtError));
      }
    } finally {
      if (isMountedRef.current) {
        if (reason === "initial") {
          setIsLoading(false);
        }
        if (reason === "manual") {
          setIsRefreshing(false);
        }
      }
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    void loadStats("initial");
    const intervalId = window.setInterval(() => void loadStats("poll"), POLL_INTERVAL_MS);
    return () => {
      isMountedRef.current = false;
      window.clearInterval(intervalId);
    };
  }, [loadStats]);

  return (
    <section className="space-y-4 sm:space-y-6">
      <PageHeader
        actions={
          <Button
            className="gap-2"
            disabled={isRefreshing}
            onClick={() => void loadStats("manual")}
            variant="secondary"
          >
            <RefreshCw aria-hidden="true" className={cn("h-4 w-4", isRefreshing ? "animate-spin" : "")} />
            {isRefreshing ? "refreshing" : "refresh"}
          </Button>
        }
        description={`last updated: ${lastUpdated}`}
        status={stats?.isRaspberryPi ? <StatusBadge label="raspberry pi" tone="info" /> : null}
        title="system_metrics"
      />

      {error && !stats ? (
        <Card className="border-danger/30">
          <CardContent className="flex flex-col items-start gap-3 p-4 sm:p-6">
            <p className="text-sm font-medium text-danger">Unable to load system metrics</p>
            <p className="text-sm text-muted-foreground">{error}</p>
            <Button onClick={() => void loadStats("manual")} variant="outline">
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {error && stats ? (
        <Card aria-live="polite" className="border-warning/30" role="status">
          <CardContent className="p-4 text-sm text-warning">Refresh failed: {error}</CardContent>
        </Card>
      ) : null}

      {stats?.warnings.length ? (
        <Card aria-live="polite" className="border-warning/30" role="status">
          <CardContent className="flex items-start gap-3 p-4 text-sm text-warning">
            <TriangleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="space-y-1">
              {stats.warnings.map((warning) => (
                <p key={`${warning.metric}:${warning.source}`}>{warning.message}</p>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {isLoading ? (
        <Card aria-live="polite" role="status">
          <CardContent className="flex min-h-[14rem] items-center justify-center p-6 text-sm text-muted-foreground">
            Loading system metrics...
          </CardContent>
        </Card>
      ) : stats ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              detail={stats.cpuFreqMhz ? `${Math.round(stats.cpuFreqMhz)} MHz` : undefined}
              label="cpu"
              percent={stats.cpuPercent}
              value={formatPercent(stats.cpuPercent)}
            />
            <MetricCard
              detail={usageDetail(stats.memory)}
              label="mem"
              percent={stats.memory.percent}
              value={formatPercent(stats.memory.percent)}
            />
            <MetricCard
              label="temp"
              percent={stats.temperatureCelsius}
              tone={getMetricTone(stats.temperatureCelsius)}
              value={stats.temperatureCelsius === null ? "—" : `${stats.temperatureCelsius.toFixed(1)} °C`}
            />
            <MetricCard
              detail={usageDetail(stats.disk)}
              label="storage"
              percent={stats.disk.percent}
              value={formatPercent(stats.disk.percent)}
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle className="text-base sm:text-lg">CPU cores</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {stats.perCore.length ? (
                  stats.perCore.map((core, index) => (
                    <div className="flex items-center gap-3" key={index}>
                      <span className="w-12 font-mono text-xs text-muted-foreground">cpu{index}</span>
                      <MetricBar
                        className="flex-1"
                        label={`cpu${index}`}
                        tone={getMetricTone(core)}
                        value={core}
                      />
                      <span className="w-12 text-right font-mono text-xs text-muted-foreground">
                        {formatPercent(core)}
                      </span>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-muted-foreground">Per-core data unavailable.</p>
                )}
                {stats.throttling ? (
                  <Badge tone={stats.throttling.toLowerCase().includes("ok") ? "success" : "warning"}>
                    throttling: {stats.throttling}
                  </Badge>
                ) : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base sm:text-lg">Storage</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <MetricCard
                  detail={usageDetail(stats.disk)}
                  label="primary"
                  percent={stats.disk.percent}
                  value={formatPercent(stats.disk.percent)}
                />
                <MetricCard
                  detail={usageDetail(stats.disk2)}
                  label="secondary"
                  percent={stats.disk2.percent}
                  value={formatPercent(stats.disk2.percent)}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base sm:text-lg">Network I/O</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-muted-foreground">↓ received</span>
                  <span className="font-mono text-success">{formatBytes(stats.networkReceived)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-muted-foreground">↑ sent</span>
                  <span className="font-mono text-info">{formatBytes(stats.networkSent)}</span>
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      ) : null}
    </section>
  );
}
