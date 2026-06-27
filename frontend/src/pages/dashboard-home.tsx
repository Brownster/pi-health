import { useCallback, useEffect, useMemo, useState } from "react";
import { ExternalLink, RefreshCw, Server, TriangleAlert } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { MetricBar } from "@/components/ui/metric-bar";
import { PageHeader } from "@/components/ui/page-header";
import { type ContainerSummary, fetchContainers, getContainerWebPort } from "@/lib/containers";
import { formatBytes, formatClockTime, formatPercent } from "@/lib/format";
import { fetchSystemStats, type SystemStats } from "@/lib/system";
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 30_000;

const serviceNames: Record<string, string> = {
  transmission: "Transmission",
  jackett: "Jackett",
  sonarr: "Sonarr",
  radarr: "Radarr",
  nzbget: "NZBGet",
  jellyfin: "Jellyfin",
  get_iplayer: "Get iPlayer",
  rtdclient: "RTD Client",
  rdtclient: "RDT Client",
  lidarr: "Lidarr",
  audiobookshelf: "Audiobookshelf",
  "airsonic-advanced": "Airsonic",
};

type MetricTone = "primary" | "success" | "warning" | "danger" | "info";

function getFriendlyName(name: string): string {
  return (
    serviceNames[name.toLowerCase()] ??
    name
      .replace(/[-_]+/g, " ")
      .replace(/\b\w/g, (character) => character.toUpperCase())
  );
}

function getTone(value: number | null, warningAt: number, dangerAt: number): MetricTone {
  if (value === null) {
    return "primary";
  }
  if (value >= dangerAt) {
    return "danger";
  }
  if (value >= warningAt) {
    return "warning";
  }
  return "success";
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
  return error instanceof Error && error.message ? error.message : "Request failed";
}

function MetricCard({
  label,
  value,
  percent,
  tone,
  detail,
}: {
  label: string;
  value: string;
  percent: number | null;
  tone: MetricTone;
  detail?: string;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="font-mono text-[11px] uppercase tracking-[0.1em] text-muted-foreground">
          {label}
        </p>
        <div className="mt-1 flex min-h-8 items-baseline justify-between gap-3">
          <p className={cn("font-mono text-xl font-medium", getToneTextClass(tone))}>{value}</p>
          {detail ? <p className="truncate font-mono text-[10px] text-dim">{detail}</p> : null}
        </div>
        <MetricBar className="mt-2" label={`${label} ${value}`} tone={tone} value={percent} />
      </CardContent>
    </Card>
  );
}

function ServiceCard({ container }: { container: ContainerSummary }) {
  const port = getContainerWebPort(container);
  const isRunning = container.status === "running";
  const friendlyName = getFriendlyName(container.name);
  const serviceUrl = port
    ? `http://${typeof window === "undefined" ? "localhost" : window.location.hostname}:${port}`
    : null;

  return (
    <Card className="transition-colors duration-200 hover:border-primary/25">
      <CardContent className="p-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-[#28323f] bg-muted font-mono text-sm font-semibold text-primary">
            {friendlyName.charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0">
            <h2 className="truncate text-[15px] font-semibold text-foreground">{friendlyName}</h2>
            <p className="mt-0.5 truncate font-mono text-[11px] text-dim">
              {port ? `port:${port}` : container.image}
            </p>
          </div>
        </div>

        <div className="mt-4 flex min-h-9 items-center justify-between gap-3">
          <StatusBadge
            label={container.status || "unknown"}
            tone={isRunning ? "success" : container.status === "exited" ? "danger" : "neutral"}
          />
          {serviceUrl && isRunning ? (
            <a
              className="inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-md border border-primary/25 px-3 font-mono text-xs text-primary transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              href={serviceUrl}
              rel="noopener noreferrer"
              target="_blank"
            >
              open
              <ExternalLink aria-hidden="true" className="h-3.5 w-3.5" />
            </a>
          ) : (
            <Link className={buttonVariants({ variant: "ghost", size: "sm" })} to="/containers">
              manage
            </Link>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function DashboardHomePage() {
  const [containers, setContainers] = useState<ContainerSummary[]>([]);
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const loadDashboard = useCallback(async (signal?: AbortSignal, background = false) => {
    if (!background) {
      setIsRefreshing(true);
    }

    const [containersResult, statsResult] = await Promise.allSettled([
      fetchContainers({ includeStats: false, signal }),
      fetchSystemStats(signal),
    ]);

    if (signal?.aborted) {
      return;
    }

    const nextErrors: string[] = [];
    let loaded = false;

    if (containersResult.status === "fulfilled") {
      setContainers(containersResult.value);
      loaded = true;
    } else {
      nextErrors.push(`Containers: ${getErrorMessage(containersResult.reason)}`);
    }

    if (statsResult.status === "fulfilled") {
      setStats(statsResult.value);
      loaded = true;
    } else {
      nextErrors.push(`System metrics: ${getErrorMessage(statsResult.reason)}`);
    }

    setErrors(nextErrors);
    if (loaded) {
      setLastUpdated(new Date());
    }
    setIsRefreshing(false);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadDashboard(controller.signal, true);
    const pollId = window.setInterval(() => void loadDashboard(controller.signal, true), POLL_INTERVAL_MS);

    return () => {
      controller.abort();
      window.clearInterval(pollId);
    };
  }, [loadDashboard]);

  const webServices = useMemo(
    () => containers.filter((container) => getContainerWebPort(container) !== null),
    [containers],
  );
  const runningServices = webServices.filter((container) => container.status === "running");

  const cpuTone = getTone(stats?.cpuPercent ?? null, 60, 85);
  const memoryTone = getTone(stats?.memory.percent ?? null, 70, 90);
  const temperature = stats?.temperatureCelsius ?? null;
  const temperatureTone = getTone(temperature, 65, 80);
  const diskTone = getTone(stats?.disk.percent ?? null, 75, 90);

  const status = !lastUpdated ? (
    <StatusBadge label="syncing" tone="info" />
  ) : errors.length ? (
    <StatusBadge label="degraded" tone="warning" />
  ) : (
    <StatusBadge label={`${runningServices.length} up`} tone="success" />
  );

  return (
    <section className="space-y-5 sm:space-y-6">
      <PageHeader
        actions={
          <Button
            className="gap-2"
            disabled={isRefreshing}
            onClick={() => void loadDashboard(undefined, false)}
            variant="secondary"
          >
            <RefreshCw aria-hidden="true" className={cn("h-4 w-4", isRefreshing && "animate-spin")} />
            refresh
          </Button>
        }
        description={
          <>
            docker · {containers.length} containers · {lastUpdated ? `synced ${formatClockTime(lastUpdated)}` : "syncing"}
          </>
        }
        status={status}
        title="web_services"
      />

      {errors.length ? (
        <Card aria-live="polite" className="border-warning/30" role="status">
          <CardContent className="flex items-start gap-3 p-4 text-sm text-warning">
            <TriangleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="space-y-1">
              {errors.map((error) => (
                <p key={error}>{error}</p>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="cpu"
          percent={stats?.cpuPercent ?? null}
          tone={cpuTone}
          value={formatPercent(stats?.cpuPercent)}
        />
        <MetricCard
          detail={stats ? `${formatBytes(stats.memory.used)} / ${formatBytes(stats.memory.total)}` : undefined}
          label="memory"
          percent={stats?.memory.percent ?? null}
          tone={memoryTone}
          value={formatPercent(stats?.memory.percent)}
        />
        <MetricCard
          label="temperature"
          percent={temperature === null ? null : (temperature / 90) * 100}
          tone={temperatureTone}
          value={temperature === null ? "—" : `${temperature.toFixed(1)} °C`}
        />
        <MetricCard
          detail={stats ? `${formatBytes(stats.disk.used)} / ${formatBytes(stats.disk.total)}` : undefined}
          label="storage"
          percent={stats?.disk.percent ?? null}
          tone={diskTone}
          value={formatPercent(stats?.disk.percent)}
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-divider pb-3">
        <div className="flex items-center gap-2">
          <Server aria-hidden="true" className="h-4 w-4 text-primary" />
          <h2 className="font-mono text-sm font-semibold text-foreground">services</h2>
        </div>
        <Badge tone="neutral">{webServices.length} detected</Badge>
      </div>

      {webServices.length ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {webServices.map((container) => (
            <ServiceCard container={container} key={container.id} />
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="flex min-h-40 flex-col items-center justify-center gap-3 p-6 text-center">
            <Server aria-hidden="true" className="h-6 w-6 text-dim" />
            <p className="text-sm text-muted-foreground">
              {lastUpdated ? "No web services detected." : "Loading services..."}
            </p>
            {lastUpdated ? (
              <Link className={buttonVariants({ variant: "outline", size: "sm" })} to="/containers">
                view containers
              </Link>
            ) : null}
          </CardContent>
        </Card>
      )}
    </section>
  );
}
