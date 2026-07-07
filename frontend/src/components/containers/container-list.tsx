import { FileText, Loader2, Wifi } from "lucide-react";

import { StatusBadge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  type ContainerAction,
  type ContainerSummary,
  getContainerWebUrl,
} from "@/lib/containers";
import { formatBytes, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface NetworkRate {
  rxRate: number | null;
  txRate: number | null;
}

export type NetworkRateMap = Record<string, NetworkRate>;

const ACTION_ORDER: ContainerAction[] = [
  "start",
  "stop",
  "restart",
  "check_update",
  "update",
];
export const ACTION_META: Record<
  ContainerAction,
  { label: string; pendingLabel: string; className: string }
> = {
  start: {
    label: "Start",
    pendingLabel: "Starting...",
    className:
      "border-success/30 bg-success/10 text-success hover:bg-success/15",
  },
  stop: {
    label: "Stop",
    pendingLabel: "Stopping...",
    className: "border-danger/30 bg-danger/10 text-danger hover:bg-danger/15",
  },
  restart: {
    label: "Restart",
    pendingLabel: "Restarting...",
    className:
      "border-warning/30 bg-warning/10 text-warning hover:bg-warning/15",
  },
  check_update: {
    label: "Check Update",
    pendingLabel: "Checking...",
    className: "border-border text-muted-foreground hover:bg-muted",
  },
  update: {
    label: "Update",
    pendingLabel: "Updating...",
    className: "border-info/30 bg-info/10 text-info hover:bg-info/15",
  },
};

function getStatusTone(status: string): BadgeProps["tone"] {
  if (status === "running") return "success";
  if (status === "stopped" || status === "exited") return "danger";
  if (status === "unavailable") return "warning";
  return "neutral";
}

function getMetricTone(percent: number | null): string {
  if (percent === null) return "text-muted-foreground";
  if (percent < 50) return "text-success";
  if (percent < 80) return "text-warning";
  return "text-danger";
}

function getMetricBarTone(percent: number | null): string {
  if (percent === null) return "bg-dim";
  if (percent < 50) return "bg-success";
  if (percent < 80) return "bg-warning";
  return "bg-danger";
}

function isUnavailable(status: string): boolean {
  return status === "unavailable" || status === "error";
}

function MetricCell({
  percent,
  detail,
}: {
  percent: number | null;
  detail?: string;
}) {
  const width = percent === null ? 0 : Math.max(0, Math.min(percent, 100));
  return (
    <div className="min-w-0 space-y-1">
      <p className={cn("text-sm font-medium", getMetricTone(percent))}>
        {formatPercent(percent)}
      </p>
      {detail ? (
        <p className="text-xs text-muted-foreground">{detail}</p>
      ) : null}
      <div className="h-1.5 rounded-full bg-muted">
        <div
          className={cn(
            "h-1.5 rounded-full transition-[width] duration-300",
            getMetricBarTone(percent),
          )}
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}

function NetworkCell({
  rate,
  rx,
  tx,
}: {
  rate?: NetworkRate;
  rx: number | null;
  tx: number | null;
}) {
  const useRate = Boolean(
    rate && (rate.rxRate !== null || rate.txRate !== null),
  );
  const down = useRate
    ? `${formatBytes(rate?.rxRate ?? null)}/s`
    : formatBytes(rx);
  const up = useRate
    ? `${formatBytes(rate?.txRate ?? null)}/s`
    : formatBytes(tx);
  return (
    <div className="space-y-1 text-xs">
      <p className="text-sky-300">
        <span aria-hidden="true">↓ </span>
        <span className="sr-only">
          {useRate ? "Download rate " : "Received "}
        </span>
        {down}
      </p>
      <p className="text-emerald-300">
        <span aria-hidden="true">↑ </span>
        <span className="sr-only">{useRate ? "Upload rate " : "Sent "}</span>
        {up}
      </p>
    </div>
  );
}

type ListProps = {
  containers: ContainerSummary[];
  networkRates: NetworkRateMap;
  pendingActions: Record<string, ContainerAction>;
  onAction: (container: ContainerSummary, action: ContainerAction) => void;
  onOpenLogs: (container: ContainerSummary) => void;
  onOpenDetails: (container: ContainerSummary) => void;
  onOpenNetworkTest: (container: ContainerSummary) => void;
};

function ActionControls({
  container,
  pendingAction,
  align,
  onAction,
}: {
  container: ContainerSummary;
  pendingAction?: ContainerAction;
  align: "start" | "end";
  onAction: ListProps["onAction"];
}) {
  const busy = Boolean(pendingAction);
  return (
    <div
      className={cn(
        "flex flex-wrap gap-2",
        align === "end" ? "justify-end" : "justify-start",
      )}
    >
      {ACTION_ORDER.map((action) => {
        const meta = ACTION_META[action];
        const disabled =
          busy ||
          isUnavailable(container.status) ||
          (action === "start" && container.status === "running") ||
          (action === "stop" &&
            (container.status === "stopped" || container.status === "exited"));
        return (
          <Button
            aria-label={`${meta.label} ${container.name}`}
            className={cn(
              "gap-1.5 px-2.5 text-xs sm:px-3 sm:text-sm",
              meta.className,
            )}
            data-action={action}
            data-container-id={container.id}
            disabled={disabled}
            key={action}
            onClick={() => onAction(container, action)}
            size="sm"
            variant="outline"
          >
            {pendingAction === action ? (
              <Loader2
                aria-hidden="true"
                className="h-3.5 w-3.5 animate-spin"
              />
            ) : null}
            {pendingAction === action ? meta.pendingLabel : meta.label}
          </Button>
        );
      })}
    </div>
  );
}

function DiagnosticControls({
  container,
  busy,
  align,
  onOpenLogs,
  onOpenNetworkTest,
}: {
  container: ContainerSummary;
  busy: boolean;
  align: "start" | "end";
  onOpenLogs: ListProps["onOpenLogs"];
  onOpenNetworkTest: ListProps["onOpenNetworkTest"];
}) {
  const disabled = busy || isUnavailable(container.status);
  return (
    <div
      className={cn(
        "flex flex-wrap gap-2",
        align === "end" ? "justify-end" : "justify-start",
      )}
    >
      <Button
        aria-label={`Logs ${container.name}`}
        className="gap-1.5 text-xs sm:text-sm"
        data-container-id={container.id}
        data-diagnostic-action="logs"
        disabled={disabled}
        onClick={() => onOpenLogs(container)}
        size="sm"
        variant="outline"
      >
        <FileText aria-hidden="true" className="h-3.5 w-3.5" />
        Logs
      </Button>
      <Button
        aria-label={`Network Test ${container.name}`}
        className="gap-1.5 text-xs sm:text-sm"
        data-container-id={container.id}
        data-diagnostic-action="network-test"
        disabled={disabled}
        onClick={() => onOpenNetworkTest(container)}
        size="sm"
        variant="outline"
      >
        <Wifi aria-hidden="true" className="h-3.5 w-3.5" />
        Network Test
      </Button>
    </div>
  );
}

function WebLink({
  container,
  mobile = false,
}: {
  container: ContainerSummary;
  mobile?: boolean;
}) {
  const url = getContainerWebUrl(container);
  if (!url)
    return (
      <span className="text-xs text-muted-foreground">
        {mobile ? "Web UI unavailable" : "N/A"}
      </span>
    );
  return (
    <a
      aria-label={`Open ${container.name} web UI in a new tab`}
      className={
        mobile
          ? "inline-flex min-h-11 items-center rounded-md border border-border px-3 text-sm text-primary underline-offset-2 hover:bg-muted hover:underline"
          : "inline-flex min-h-11 items-center text-sm text-primary underline-offset-2 hover:underline"
      }
      href={url}
      rel="noopener noreferrer"
      target="_blank"
    >
      {mobile ? "Open Web UI" : "Open"}
    </a>
  );
}

export function ContainerList(props: ListProps) {
  const {
    containers,
    networkRates,
    pendingActions,
    onAction,
    onOpenLogs,
    onOpenDetails,
    onOpenNetworkTest,
  } = props;
  return (
    <>
      <div className="hidden xl:block">
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="min-w-full divide-y divide-divider text-sm">
            <thead className="bg-[#0e131a]">
              <tr>
                {[
                  "Container",
                  "Image",
                  "Status",
                  "CPU",
                  "Memory",
                  "Network",
                  "Web UI",
                  "Actions",
                ].map((heading) => (
                  <th
                    className={cn(
                      "px-4 py-3 font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-dim",
                      heading === "Actions" ? "text-right" : "text-left",
                    )}
                    key={heading}
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-divider">
              {containers.map((container) => {
                const pending = pendingActions[container.id];
                return (
                  <tr key={container.id}>
                    <td className="px-4 py-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <button
                          className="truncate font-medium text-primary hover:underline"
                          onClick={() => onOpenDetails(container)}
                        >
                          {container.name}
                        </button>
                        {container.health ? (
                          <span
                            aria-label={`Health ${container.health}`}
                            className={cn(
                              "h-2.5 w-2.5 shrink-0 rounded-full",
                              container.health === "healthy"
                                ? "bg-success"
                                : container.health === "unhealthy"
                                  ? "bg-danger"
                                  : "bg-warning",
                            )}
                            title={`Health: ${container.health}`}
                          />
                        ) : null}
                        {container.update_available ? (
                          <span
                            aria-label="Update available"
                            className="text-amber-300"
                            role="img"
                            title="Update available"
                          >
                            ↻
                          </span>
                        ) : null}
                      </div>
                    </td>
                    <td className="max-w-[20rem] px-4 py-3 text-muted-foreground">
                      <span className="line-clamp-2 break-all">
                        {container.image}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge
                        label={container.status}
                        tone={getStatusTone(container.status)}
                      />
                    </td>
                    <td className="px-4 py-3">
                      <MetricCell percent={container.cpu_percent} />
                    </td>
                    <td className="px-4 py-3">
                      <MetricCell
                        detail={`${formatBytes(container.memory_used)} / ${formatBytes(container.memory_limit)}`}
                        percent={container.memory_percent}
                      />
                    </td>
                    <td className="px-4 py-3">
                      <NetworkCell
                        rate={networkRates[container.id]}
                        rx={container.net_rx}
                        tx={container.net_tx}
                      />
                    </td>
                    <td className="px-4 py-3">
                      <WebLink container={container} />
                    </td>
                    <td className="space-y-2 px-4 py-3 text-right">
                      <ActionControls
                        align="end"
                        container={container}
                        onAction={onAction}
                        pendingAction={pending}
                      />
                      <DiagnosticControls
                        align="end"
                        busy={Boolean(pending)}
                        container={container}
                        onOpenLogs={onOpenLogs}
                        onOpenNetworkTest={onOpenNetworkTest}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      <div className="grid gap-3 xl:hidden">
        {containers.map((container) => {
          const pending = pendingActions[container.id];
          return (
            <Card className="overflow-hidden" key={container.id}>
              <CardContent className="space-y-3 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <button
                      className="truncate text-left text-sm font-semibold text-primary hover:underline"
                      onClick={() => onOpenDetails(container)}
                    >
                      {container.name}
                    </button>
                    <p className="line-clamp-2 break-all text-xs text-muted-foreground">
                      {container.image}
                    </p>
                  </div>
                  <StatusBadge
                    className="shrink-0"
                    label={container.status}
                    tone={getStatusTone(container.status)}
                  />
                </div>
                <div className="grid gap-2 text-xs sm:grid-cols-2">
                  <div className="space-y-1 rounded-md border border-border bg-muted/20 p-2">
                    <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-dim">
                      CPU
                    </p>
                    <MetricCell percent={container.cpu_percent} />
                  </div>
                  <div className="space-y-1 rounded-md border border-border bg-muted/20 p-2">
                    <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-dim">
                      Memory
                    </p>
                    <MetricCell
                      detail={`${formatBytes(container.memory_used)} / ${formatBytes(container.memory_limit)}`}
                      percent={container.memory_percent}
                    />
                  </div>
                </div>
                <div className="grid gap-1 rounded-md border border-border bg-muted/20 p-2 text-xs">
                  <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-dim">
                    Network
                  </p>
                  <NetworkCell
                    rate={networkRates[container.id]}
                    rx={container.net_rx}
                    tx={container.net_tx}
                  />
                </div>
                <div className="grid gap-2 sm:flex sm:items-center sm:justify-between">
                  <WebLink container={container} mobile />
                </div>
                <ActionControls
                  align="start"
                  container={container}
                  onAction={onAction}
                  pendingAction={pending}
                />
                <DiagnosticControls
                  align="start"
                  busy={Boolean(pending)}
                  container={container}
                  onOpenLogs={onOpenLogs}
                  onOpenNetworkTest={onOpenNetworkTest}
                />
              </CardContent>
            </Card>
          );
        })}
      </div>
    </>
  );
}
