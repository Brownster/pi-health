import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Boxes,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  ExternalLink,
  Gauge,
  Layers3,
  Server,
  TriangleAlert,
} from "lucide-react";
import { Link } from "react-router-dom";

import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { MetricBar } from "@/components/ui/metric-bar";
import { PageHeader } from "@/components/ui/page-header";
import { RefreshControls } from "@/components/ui/refresh-controls";
import { formatBytes, formatClockTime, formatPercent } from "@/lib/format";
import {
  type OverviewAlertRecord,
  type OverviewApplication,
  type OverviewHealthState,
  type OverviewIssue,
  fetchOverview,
  getOverviewApplicationUrl,
  type OverviewSnapshot,
} from "@/lib/overview";
import { cn } from "@/lib/utils";

const INITIAL_APPLICATION_LIMIT = 12;

const applicationNames: Record<string, string> = {
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

const healthPresentation: Record<
  OverviewHealthState,
  { label: string; detail: string; tone: "success" | "warning" | "danger" | "neutral" }
> = {
  healthy: {
    label: "All systems operational",
    detail: "Metrics, workloads, and monitored resources are healthy.",
    tone: "success",
  },
  attention: {
    label: "Attention required",
    detail: "One or more resources need review.",
    tone: "warning",
  },
  critical: {
    label: "Critical issues",
    detail: "Immediate action is recommended.",
    tone: "danger",
  },
  unknown: {
    label: "Status unavailable",
    detail: "Some health sources could not be checked.",
    tone: "neutral",
  },
};

function getFriendlyName(name: string): string {
  return (
    applicationNames[name.toLowerCase()] ??
    name.replace(/[-_]+/g, " ").replace(/\b\w/g, (character) => character.toUpperCase())
  );
}

function getTone(value: number | null, warningAt: number, dangerAt: number): MetricTone {
  if (value === null) {
    return "info";
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
  return error instanceof Error && error.message ? error.message : "Unable to load Overview";
}

function formatEventTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "time unavailable";
  }
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return formatClockTime(date);
  }
  return new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" }).format(date);
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
    <Link className="group block focus-visible:outline-none" to="/system">
      <Card className="h-full transition-colors group-hover:border-[#303b48] group-focus-visible:ring-2 group-focus-visible:ring-ring">
        <CardContent className="p-4">
          <div className="flex items-center justify-between gap-2">
            <p className="font-mono text-[11px] uppercase text-muted-foreground">{label}</p>
            <Gauge aria-hidden="true" className="h-3.5 w-3.5 text-dim transition-colors group-hover:text-primary" />
          </div>
          <div className="mt-1 flex min-h-8 items-baseline justify-between gap-3">
            <p className={cn("font-mono text-xl font-medium", getToneTextClass(tone))}>{value}</p>
            {detail ? <p className="truncate font-mono text-[10px] text-dim">{detail}</p> : null}
          </div>
          <MetricBar className="mt-2" label={`${label} ${value}`} tone={tone} value={percent} />
        </CardContent>
      </Card>
    </Link>
  );
}

function HealthSummary({ state, issues }: { state: OverviewHealthState; issues: OverviewIssue[] }) {
  const presentation = healthPresentation[state];
  const icon = state === "healthy" ? CheckCircle2 : state === "critical" ? CircleAlert : TriangleAlert;
  const Icon = icon;
  const toneClasses = {
    success: "border-success/60 bg-success/[0.06] text-success",
    warning: "border-warning/60 bg-warning/[0.06] text-warning",
    danger: "border-danger/60 bg-danger/[0.06] text-danger",
    neutral: "border-muted-foreground/40 bg-muted/40 text-muted-foreground",
  }[presentation.tone];

  return (
    <section aria-labelledby="overview-health-title" className={cn("border-l-2", toneClasses)}>
      <div className="flex flex-col gap-4 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <div className="flex min-w-0 items-start gap-3">
          <Icon aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0" />
          <div className="min-w-0">
            <h2 className="font-mono text-base font-semibold text-foreground" id="overview-health-title">
              {presentation.label}
            </h2>
            <p className="mt-0.5 text-sm text-muted-foreground">{presentation.detail}</p>
          </div>
        </div>
        <Badge tone={presentation.tone}>{issues.length} {issues.length === 1 ? "issue" : "issues"}</Badge>
      </div>
      {issues.length ? (
        <div className="grid border-t border-current/15 sm:grid-cols-2 xl:grid-cols-3">
          {issues.slice(0, 3).map((issue) => (
            <Link
              className="flex min-w-0 items-center justify-between gap-3 border-b border-current/10 px-4 py-2.5 text-sm transition-colors hover:bg-white/[0.025] sm:border-r sm:px-5 xl:border-b-0"
              key={issue.code}
              to={issue.path}
            >
              <span className="min-w-0 truncate text-foreground">{issue.label}</span>
              <span className="shrink-0 font-mono text-[10px] uppercase text-current">review</span>
            </Link>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function AlertRow({ record, recovered = false }: { record: OverviewAlertRecord; recovered?: boolean }) {
  return (
    <div className="flex min-w-0 items-start gap-3 border-t border-divider py-3 first:border-t-0 first:pt-0 last:pb-0">
      <span
        aria-hidden="true"
        className={cn(
          "mt-1.5 h-2 w-2 shrink-0 rounded-full",
          recovered ? "bg-success" : record.severity === "critical" ? "bg-danger" : "bg-warning",
        )}
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-foreground">{record.summary}</p>
        <p className="mt-0.5 font-mono text-[10px] text-dim">
          {recovered ? "resolved" : record.kind} · {formatEventTime(record.at)}
        </p>
      </div>
    </div>
  );
}

function ApplicationLauncher({ application }: { application: OverviewApplication }) {
  const name = getFriendlyName(application.name);
  const isRunning = application.status === "running";
  const url = getOverviewApplicationUrl(application);
  const content = (
    <>
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded border border-[#2a3440] bg-muted font-mono text-xs font-semibold text-primary">
        {name.charAt(0).toUpperCase()}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-foreground">{name}</span>
        <span className="mt-0.5 flex items-center gap-1.5 font-mono text-[10px] text-dim">
          <span className={cn("h-1.5 w-1.5 rounded-full", isRunning ? "bg-success" : "bg-danger")} />
          {application.status}
        </span>
      </span>
      {url && isRunning ? <ExternalLink aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-dim" /> : null}
    </>
  );
  const className = "flex min-h-14 min-w-0 items-center gap-3 rounded-md border border-border bg-card px-3 py-2 transition-colors hover:border-[#303b48] hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

  if (url && isRunning) {
    return <a className={className} href={url} rel="noopener noreferrer" target="_blank">{content}</a>;
  }
  return <Link className={className} to="/containers">{content}</Link>;
}

export function DashboardHomePage() {
  const [snapshot, setSnapshot] = useState<OverviewSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [showAllApplications, setShowAllApplications] = useState(false);

  const loadOverview = useCallback(async (reason: "initial" | "manual" | "poll", signal?: AbortSignal) => {
    if (reason !== "poll") {
      setIsRefreshing(true);
    }
    try {
      const next = await fetchOverview(signal);
      if (signal?.aborted) {
        return;
      }
      setSnapshot(next);
      setError(null);
      const collectedAt = new Date(next.collected_at);
      setLastUpdated(Number.isNaN(collectedAt.getTime()) ? new Date() : collectedAt);
    } catch (caughtError) {
      if (!signal?.aborted) {
        setError(getErrorMessage(caughtError));
      }
    } finally {
      if (!signal?.aborted && reason !== "poll") {
        setIsRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadOverview("initial", controller.signal);
    return () => controller.abort();
  }, [loadOverview]);

  const applications = useMemo(
    () => showAllApplications
      ? (snapshot?.applications ?? [])
      : (snapshot?.applications ?? []).slice(0, INITIAL_APPLICATION_LIMIT),
    [showAllApplications, snapshot?.applications],
  );

  const metrics = snapshot?.metrics;
  const temperature = metrics?.temperature_celsius ?? null;
  const healthState = snapshot?.health.state ?? "unknown";
  const headerStatus = !snapshot ? (
    <StatusBadge label="syncing" tone="info" />
  ) : (
    <StatusBadge
      label={healthState}
      tone={healthState === "healthy" ? "success" : healthState === "critical" ? "danger" : healthState === "attention" ? "warning" : "neutral"}
    />
  );

  return (
    <section className="space-y-5 sm:space-y-6">
      <PageHeader
        actions={
          <RefreshControls
            isRefreshing={isRefreshing}
            onRefresh={() => void loadOverview("manual")}
          />
        }
        description={lastUpdated ? `last updated: ${formatClockTime(lastUpdated)}` : "collecting current status"}
        status={headerStatus}
        title="overview"
      />

      {error ? (
        <div aria-live="polite" className="flex items-start gap-3 border-l-2 border-danger bg-danger/[0.06] p-4 text-sm text-danger" role="status">
          <TriangleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-medium">Overview refresh failed</p>
            <p className="mt-0.5 text-muted-foreground">{error}</p>
          </div>
        </div>
      ) : null}

      {snapshot ? <HealthSummary issues={snapshot.health.issues} state={snapshot.health.state} /> : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="cpu"
          percent={metrics?.cpu_percent ?? null}
          tone={getTone(metrics?.cpu_percent ?? null, 60, 85)}
          value={formatPercent(metrics?.cpu_percent)}
        />
        <MetricCard
          detail={metrics ? `${formatBytes(metrics.memory_used)} / ${formatBytes(metrics.memory_total)}` : undefined}
          label="memory"
          percent={metrics?.memory_percent ?? null}
          tone={getTone(metrics?.memory_percent ?? null, 70, 90)}
          value={formatPercent(metrics?.memory_percent)}
        />
        <MetricCard
          label="temperature"
          percent={temperature === null ? null : (temperature / 90) * 100}
          tone={getTone(temperature, 65, 80)}
          value={temperature === null ? "—" : `${temperature.toFixed(1)} °C`}
        />
        <MetricCard
          detail={metrics ? `${formatBytes(metrics.disk_used)} / ${formatBytes(metrics.disk_total)}` : undefined}
          label="storage"
          percent={metrics?.disk_percent ?? null}
          tone={getTone(metrics?.disk_percent ?? null, 75, 90)}
          value={formatPercent(metrics?.disk_percent)}
        />
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        <Card>
          <CardContent className="p-4 sm:p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Activity aria-hidden="true" className="h-4 w-4 text-primary" />
                <h2 className="font-mono text-sm font-semibold">workloads</h2>
              </div>
              <Badge tone="neutral">current</Badge>
            </div>
            <div className="mt-4 grid divide-y divide-divider sm:grid-cols-2 sm:divide-x sm:divide-y-0">
              <Link className="pb-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:pb-0 sm:pr-5" to="/containers">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-sm text-muted-foreground"><Boxes aria-hidden="true" className="h-4 w-4" /> containers</span>
                  <span className="font-mono text-2xl text-foreground">{snapshot?.workloads.containers.total ?? "—"}</span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Badge tone="success">{snapshot?.workloads.containers.running ?? 0} running</Badge>
                  <Badge tone={(snapshot?.workloads.containers.unhealthy ?? 0) > 0 ? "danger" : "neutral"}>{snapshot?.workloads.containers.unhealthy ?? 0} unhealthy</Badge>
                  <Badge tone={(snapshot?.workloads.containers.stopped ?? 0) > 0 ? "warning" : "neutral"}>{snapshot?.workloads.containers.stopped ?? 0} stopped</Badge>
                </div>
              </Link>
              <Link className="pt-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:pl-5 sm:pt-0" to="/stacks">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-sm text-muted-foreground"><Layers3 aria-hidden="true" className="h-4 w-4" /> stacks</span>
                  <span className="font-mono text-2xl text-foreground">{snapshot?.workloads.stacks.total ?? "—"}</span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Badge tone="success">{snapshot?.workloads.stacks.healthy ?? 0} healthy</Badge>
                  <Badge tone={(snapshot?.workloads.stacks.partial ?? 0) > 0 ? "warning" : "neutral"}>{snapshot?.workloads.stacks.partial ?? 0} partial</Badge>
                  <Badge tone={(snapshot?.workloads.stacks.down ?? 0) > 0 ? "danger" : "neutral"}>{snapshot?.workloads.stacks.down ?? 0} down</Badge>
                </div>
              </Link>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4 sm:p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <TriangleAlert aria-hidden="true" className="h-4 w-4 text-primary" />
                <h2 className="font-mono text-sm font-semibold">alerts</h2>
              </div>
              <Link className="font-mono text-[11px] text-muted-foreground hover:text-primary" to="/integrations">view policy</Link>
            </div>
            <div className="mt-4">
              {snapshot?.alerts.active.length ? (
                snapshot.alerts.active.slice(0, 3).map((record) => <AlertRow key={record.key} record={record} />)
              ) : (
                <div className="flex items-center gap-3 py-1 text-sm text-muted-foreground">
                  <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-success" />
                  No active alerts.
                </div>
              )}
              {snapshot?.alerts.recent_recoveries.length ? (
                <div className="mt-4 border-t border-divider pt-3">
                  <p className="mb-3 font-mono text-[10px] uppercase text-dim">recently resolved</p>
                  {snapshot.alerts.recent_recoveries.map((record) => <AlertRow key={`${record.key}:${record.at}`} record={record} recovered />)}
                </div>
              ) : null}
            </div>
          </CardContent>
        </Card>
      </div>

      {snapshot?.warnings.length ? (
        <div className="flex items-start gap-3 border-l-2 border-warning/60 bg-warning/[0.04] px-4 py-3 text-sm">
          <TriangleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <p className="text-muted-foreground">
            <span className="font-medium text-warning">Data gaps:</span>{" "}
            {snapshot.warnings.slice(0, 3).map((warning) => warning.message).join(" · ")}
          </p>
        </div>
      ) : null}

      <section aria-labelledby="applications-title">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-divider pb-3">
          <div className="flex items-center gap-2">
            <Server aria-hidden="true" className="h-4 w-4 text-primary" />
            <h2 className="font-mono text-sm font-semibold" id="applications-title">applications</h2>
          </div>
          <Badge tone="neutral">{snapshot?.applications.length ?? 0} detected</Badge>
        </div>

        {applications.length ? (
          <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {applications.map((application) => <ApplicationLauncher application={application} key={application.id} />)}
          </div>
        ) : (
          <div className="mt-3 flex min-h-24 items-center justify-center rounded-md border border-border bg-card p-5 text-sm text-muted-foreground">
            {snapshot ? "No web applications detected." : "Loading applications..."}
          </div>
        )}

        {(snapshot?.applications.length ?? 0) > INITIAL_APPLICATION_LIMIT ? (
          <div className="mt-3 flex justify-center">
            <Button className="gap-2" onClick={() => setShowAllApplications((current) => !current)} size="sm" variant="ghost">
              {showAllApplications ? <ChevronUp aria-hidden="true" className="h-4 w-4" /> : <ChevronDown aria-hidden="true" className="h-4 w-4" />}
              {showAllApplications ? "show less" : `show ${(snapshot?.applications.length ?? 0) - INITIAL_APPLICATION_LIMIT} more`}
            </Button>
          </div>
        ) : null}
      </section>
    </section>
  );
}
