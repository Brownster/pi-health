import { Activity, CircleAlert, Clock3 } from "lucide-react";

import { StatusBadge, type BadgeProps } from "@/components/ui/badge";
import { MetricBar } from "@/components/ui/metric-bar";
import type { CapabilityHealthState, CapabilityStatus } from "@/lib/capabilities";
import { metricPercent } from "@/lib/capability-renderer";
import { cn } from "@/lib/utils";

function healthTone(state: CapabilityHealthState): BadgeProps["tone"] {
  if (state === "healthy") return "success";
  if (state === "warning" || state === "unconfigured") return "warning";
  if (state === "error" || state === "unavailable" || state === "incompatible") return "danger";
  return "neutral";
}

function issueClass(severity: "info" | "warning" | "error"): string {
  if (severity === "error") return "border-danger text-danger";
  if (severity === "warning") return "border-warning text-warning";
  return "border-info text-info";
}

function activityClass(kind: "info" | "success" | "warning" | "error"): string {
  if (kind === "success") return "bg-success";
  if (kind === "warning") return "bg-warning";
  if (kind === "error") return "bg-danger";
  return "bg-info";
}

function formatObservedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
}

export function CapabilityStatusPanel({ status }: { status: CapabilityStatus }) {
  const titleId = `${status.provider_id}-${status.capability_id.split(".").join("-")}-status-title`;
  return (
    <section aria-labelledby={titleId} className="rounded-lg border border-border bg-card">
      <header className="flex flex-col gap-3 border-b border-border px-4 py-4 sm:flex-row sm:items-start sm:justify-between sm:px-5">
        <div className="min-w-0">
          <h2 className="font-mono text-sm font-semibold" id={titleId}>
            Provider status
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">{status.health.message}</p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <StatusBadge label={status.health.state} tone={healthTone(status.health.state)} />
          <span className="flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
            <Clock3 aria-hidden="true" className="h-3.5 w-3.5" />
            <time dateTime={status.observed_at}>{formatObservedAt(status.observed_at)}</time>
          </span>
        </div>
      </header>

      <div className="space-y-5 px-4 py-5 sm:px-5">
        {status.summary.length ? (
          <dl className="grid grid-cols-2 border border-border sm:grid-cols-3 lg:grid-cols-4">
            {status.summary.map((item) => (
              <div className="min-w-0 border-b border-r border-border p-3 last:border-r-0" key={item.id}>
                <dt className="font-mono text-[10px] uppercase text-muted-foreground">{item.label}</dt>
                <dd
                  className={cn(
                    "mt-1 break-words text-sm font-medium tabular-nums",
                    item.tone === "success" && "text-success",
                    item.tone === "warning" && "text-warning",
                    item.tone === "danger" && "text-danger",
                  )}
                >
                  {item.value === null ? "Not available" : String(item.value)}
                  {item.unit ? ` ${item.unit}` : ""}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}

        {status.metrics.length ? (
          <div>
            <h3 className="font-mono text-xs font-semibold uppercase text-muted-foreground">Metrics</h3>
            <div className="mt-3 grid grid-cols-1 gap-x-6 gap-y-4 md:grid-cols-2">
              {status.metrics.map((metric) => {
                const percent = metricPercent(metric.value, metric.minimum, metric.maximum);
                return (
                  <div className="space-y-1.5" key={metric.id}>
                    <div className="flex items-baseline justify-between gap-3 text-sm">
                      <span>{metric.label}</span>
                      <span className="font-mono text-xs tabular-nums text-muted-foreground">
                        {metric.value}{metric.unit ? ` ${metric.unit}` : ""}
                      </span>
                    </div>
                    <MetricBar label={metric.label} value={percent} />
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}

        {status.health.issues.length ? (
          <div className="space-y-2" aria-label="Provider issues">
            {status.health.issues.map((issue) => (
              <div className={cn("border-l-2 bg-muted/20 px-3 py-2.5", issueClass(issue.severity))} key={issue.code}>
                <p className="flex items-start gap-2 text-sm font-medium">
                  <CircleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
                  {issue.message}
                </p>
                {issue.recovery ? <p className="mt-1 pl-6 text-xs text-muted-foreground">{issue.recovery}</p> : null}
              </div>
            ))}
          </div>
        ) : null}

        {status.recent_activity.length ? (
          <div>
            <h3 className="flex items-center gap-1.5 font-mono text-xs font-semibold uppercase text-muted-foreground">
              <Activity aria-hidden="true" className="h-3.5 w-3.5" />
              Recent activity
            </h3>
            <ol className="mt-3 divide-y divide-border border-y border-border">
              {status.recent_activity.map((item) => (
                <li className="flex items-start gap-3 py-2.5 text-sm" key={item.id}>
                  <span aria-hidden="true" className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", activityClass(item.kind))} />
                  <span className="min-w-0 flex-1 break-words">{item.summary}</span>
                  <time className="shrink-0 font-mono text-[10px] text-muted-foreground" dateTime={item.occurred_at}>
                    {formatObservedAt(item.occurred_at)}
                  </time>
                </li>
              ))}
            </ol>
          </div>
        ) : null}
      </div>
    </section>
  );
}
