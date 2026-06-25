import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Activity, FileText, Loader2, RefreshCw, Server, TriangleAlert, Wifi } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  type ContainerAction,
  type ContainerActionResult,
  type ContainerFilter,
  type ContainerNetworkTestResult,
  type ContainerSummary,
  type HostNetworkTestResult,
  fetchContainerLogs,
  fetchContainerStats,
  fetchContainers,
  filterContainers,
  getContainerWebPort,
  runContainerAction,
  runContainerNetworkTest,
  runHostNetworkTest,
} from "@/lib/containers";
import { formatBytes, formatClockTime, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 10_000;
const FILTER_ITEMS: Array<{ key: ContainerFilter; label: string }> = [
  { key: "all", label: "All" },
  { key: "running", label: "Running" },
  { key: "stopped", label: "Stopped" },
];
const ACTION_ORDER: ContainerAction[] = [
  "start",
  "stop",
  "restart",
  "check_update",
  "update",
];

const ACTION_META: Record<
  ContainerAction,
  {
    label: string;
    pendingLabel: string;
    className: string;
  }
> = {
  start: {
    label: "Start",
    pendingLabel: "Starting...",
    className: "border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/15",
  },
  stop: {
    label: "Stop",
    pendingLabel: "Stopping...",
    className: "border-amber-500/40 text-amber-300 hover:bg-amber-500/15",
  },
  restart: {
    label: "Restart",
    pendingLabel: "Restarting...",
    className: "border-sky-500/40 text-sky-300 hover:bg-sky-500/15",
  },
  check_update: {
    label: "Check Update",
    pendingLabel: "Checking...",
    className: "border-slate-500/50 text-slate-200 hover:bg-slate-500/15",
  },
  update: {
    label: "Update",
    pendingLabel: "Updating...",
    className: "border-violet-500/40 text-violet-300 hover:bg-violet-500/15",
  },
};

type AsyncStatus = "idle" | "loading" | "ready" | "error";

type ActionNotice = {
  message: string;
  tone: "info" | "success" | "error";
};

interface NetworkRate {
  rxRate: number | null;
  txRate: number | null;
}

type NetworkRateMap = Record<string, NetworkRate>;

interface LogsModalState {
  open: boolean;
  status: AsyncStatus;
  containerId: string | null;
  containerName: string;
  logs: string;
  error: string | null;
}

interface ContainerNetworkModalState {
  open: boolean;
  status: AsyncStatus;
  containerId: string | null;
  containerName: string;
  result: ContainerNetworkTestResult | null;
  error: string | null;
}

interface HostNetworkPanelState {
  visible: boolean;
  status: AsyncStatus;
  result: HostNetworkTestResult | null;
  error: string | null;
}

function getStatusTone(status: string): string {
  switch (status) {
    case "running":
      return "bg-emerald-500/15 text-emerald-300 border-emerald-500/40";
    case "stopped":
    case "exited":
      return "bg-rose-500/15 text-rose-300 border-rose-500/40";
    case "unavailable":
      return "bg-amber-500/15 text-amber-300 border-amber-500/40";
    default:
      return "bg-slate-500/15 text-slate-300 border-slate-500/40";
  }
}

function getMetricTone(percent: number | null): string {
  if (percent === null) {
    return "text-muted-foreground";
  }
  if (percent < 50) {
    return "text-emerald-300";
  }
  if (percent < 80) {
    return "text-amber-300";
  }
  return "text-rose-300";
}

function getMetricBarTone(percent: number | null): string {
  if (percent === null) {
    return "bg-slate-500";
  }
  if (percent < 50) {
    return "bg-emerald-500";
  }
  if (percent < 80) {
    return "bg-amber-500";
  }
  return "bg-rose-500";
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "Unable to load containers";
}

function getNoticeToneClass(tone: ActionNotice["tone"]): string {
  if (tone === "success") {
    return "border-emerald-500/40 text-emerald-300";
  }
  if (tone === "error") {
    return "border-rose-500/40 text-rose-300";
  }
  return "border-sky-500/40 text-sky-300";
}

function isUnavailableStatus(status: string): boolean {
  return status === "unavailable" || status === "error";
}

function isActionDisabled(
  container: ContainerSummary,
  action: ContainerAction,
  rowBusy: boolean,
): boolean {
  if (rowBusy) {
    return true;
  }

  if (isUnavailableStatus(container.status)) {
    return true;
  }

  if (action === "start") {
    return container.status === "running";
  }
  if (action === "stop") {
    return container.status === "stopped" || container.status === "exited";
  }

  return false;
}

function getActionSuccessMessage(
  containerName: string,
  action: ContainerAction,
  result: ContainerActionResult,
): string {
  if (action === "check_update") {
    if (typeof result.update_available === "boolean") {
      return result.update_available
        ? `${containerName}: update available`
        : `${containerName}: up to date`;
    }
    return result.status || `${containerName}: update check complete`;
  }

  if (action === "update") {
    return result.status || `${containerName}: update triggered`;
  }

  const suffix = action === "start" ? "started" : action === "stop" ? "stopped" : "restarted";
  return result.status || `${containerName} ${suffix} successfully`;
}

function formatNetworkValue(value: string | null): string {
  return value && value.trim().length > 0 ? value : "Unavailable";
}

function formatRatePerSecond(value: number | null): string {
  if (value === null) {
    return "—";
  }
  return `${formatBytes(value)}/s`;
}

function getNetworkStatus(
  status: AsyncStatus,
  pingSuccess: boolean | null,
): { label: string; className: string } {
  if (status === "loading") {
    return { label: "Running test...", className: "text-sky-300" };
  }
  if (status === "error") {
    return { label: "Error", className: "text-rose-300" };
  }
  if (pingSuccess === null) {
    return { label: "Idle", className: "text-muted-foreground" };
  }
  return pingSuccess
    ? { label: "Success", className: "text-emerald-300" }
    : { label: "Failed", className: "text-amber-300" };
}

function NetworkCell({ rate, rx, tx }: { rate?: NetworkRate; rx: number | null; tx: number | null }) {
  const hasRate = Boolean(rate && (rate.rxRate !== null || rate.txRate !== null));

  if (hasRate) {
    return (
      <div className="space-y-1 text-xs">
        <p className="text-sky-300">
          <span aria-hidden="true">↓ </span>
          <span className="sr-only">Download rate </span>
          {formatRatePerSecond(rate?.rxRate ?? null)}
        </p>
        <p className="text-emerald-300">
          <span aria-hidden="true">↑ </span>
          <span className="sr-only">Upload rate </span>
          {formatRatePerSecond(rate?.txRate ?? null)}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-1 text-xs">
      <p className="text-sky-300">
        <span aria-hidden="true">↓ </span>
        <span className="sr-only">Received </span>
        {formatBytes(rx)}
      </p>
      <p className="text-emerald-300">
        <span aria-hidden="true">↑ </span>
        <span className="sr-only">Sent </span>
        {formatBytes(tx)}
      </p>
    </div>
  );
}

function MetricCell({
  percent,
  detail,
}: {
  percent: number | null;
  detail?: string;
}) {
  const clampedWidth = percent === null ? 0 : Math.max(0, Math.min(percent, 100));

  return (
    <div className="min-w-0 space-y-1">
      <p className={cn("text-sm font-medium", getMetricTone(percent))}>{formatPercent(percent)}</p>
      {detail ? <p className="text-xs text-muted-foreground">{detail}</p> : null}
      <div className="h-1.5 rounded-full bg-muted">
        <div
          className={cn("h-1.5 rounded-full transition-[width] duration-300", getMetricBarTone(percent))}
          style={{ width: `${clampedWidth}%` }}
        />
      </div>
    </div>
  );
}

function ContainerActionControls({
  container,
  pendingAction,
  align,
  onAction,
}: {
  container: ContainerSummary;
  pendingAction?: ContainerAction;
  align: "start" | "end";
  onAction: (container: ContainerSummary, action: ContainerAction) => void;
}) {
  const rowBusy = Boolean(pendingAction);

  return (
    <div className={cn("flex flex-wrap gap-2", align === "end" ? "justify-end" : "justify-start")}>
      {ACTION_ORDER.map((action) => {
        const meta = ACTION_META[action];
        const isCurrentAction = pendingAction === action;
        const disabled = isActionDisabled(container, action, rowBusy);

        return (
          <Button
            aria-label={`${meta.label} ${container.name}`}
            className={cn("gap-1.5 px-2.5 text-xs sm:px-3 sm:text-sm", meta.className)}
            data-action={action}
            data-container-id={container.id}
            disabled={disabled}
            key={`${container.id}-${action}`}
            onClick={() => onAction(container, action)}
            size="sm"
            variant="outline"
          >
            {isCurrentAction ? <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" /> : null}
            {isCurrentAction ? meta.pendingLabel : meta.label}
          </Button>
        );
      })}
    </div>
  );
}

function ContainerDiagnosticsControls({
  container,
  rowBusy,
  align,
  onOpenLogs,
  onOpenNetworkTest,
}: {
  container: ContainerSummary;
  rowBusy: boolean;
  align: "start" | "end";
  onOpenLogs: (container: ContainerSummary) => void;
  onOpenNetworkTest: (container: ContainerSummary) => void;
}) {
  const disabled = rowBusy || isUnavailableStatus(container.status);

  return (
    <div className={cn("flex flex-wrap gap-2", align === "end" ? "justify-end" : "justify-start")}>
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

function DesktopContainerTable({
  containers,
  networkRates,
  pendingActions,
  onAction,
  onOpenLogs,
  onOpenNetworkTest,
}: {
  containers: ContainerSummary[];
  networkRates: NetworkRateMap;
  pendingActions: Record<string, ContainerAction>;
  onAction: (container: ContainerSummary, action: ContainerAction) => void;
  onOpenLogs: (container: ContainerSummary) => void;
  onOpenNetworkTest: (container: ContainerSummary) => void;
}) {
  return (
    <div className="hidden xl:block">
      <div className="overflow-x-auto rounded-xl border border-border/70 bg-card/70">
        <table className="min-w-full divide-y divide-border/80 text-sm">
          <thead className="bg-muted/55">
            <tr>
              <th className="px-4 py-3 text-left text-xs uppercase tracking-wide text-muted-foreground">
                Container
              </th>
              <th className="px-4 py-3 text-left text-xs uppercase tracking-wide text-muted-foreground">
                Image
              </th>
              <th className="px-4 py-3 text-left text-xs uppercase tracking-wide text-muted-foreground">
                Status
              </th>
              <th className="px-4 py-3 text-left text-xs uppercase tracking-wide text-muted-foreground">
                CPU
              </th>
              <th className="px-4 py-3 text-left text-xs uppercase tracking-wide text-muted-foreground">
                Memory
              </th>
              <th className="px-4 py-3 text-left text-xs uppercase tracking-wide text-muted-foreground">
                Network
              </th>
              <th className="px-4 py-3 text-left text-xs uppercase tracking-wide text-muted-foreground">
                Web UI
              </th>
              <th className="px-4 py-3 text-right text-xs uppercase tracking-wide text-muted-foreground">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/70">
            {containers.map((container) => {
              const webPort = getContainerWebPort(container);
              const rowBusy = Boolean(pendingActions[container.id]);

              return (
                <tr key={container.id}>
                  <td className="px-4 py-3">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate font-medium">{container.name}</span>
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
                    <span className="line-clamp-2 break-all">{container.image}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full border px-2 py-1 text-xs font-medium capitalize",
                        getStatusTone(container.status),
                      )}
                    >
                      {container.status}
                    </span>
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
                    {webPort ? (
                      <a
                        aria-label={`Open ${container.name} web UI in a new tab`}
                        className="inline-flex min-h-11 items-center text-sm text-primary underline-offset-2 hover:underline"
                        href={`http://${window.location.hostname}:${webPort}`}
                        rel="noopener noreferrer"
                        target="_blank"
                      >
                        Open
                      </a>
                    ) : (
                      <span className="text-xs text-muted-foreground">N/A</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="space-y-2">
                      <ContainerActionControls
                        align="end"
                        container={container}
                        onAction={onAction}
                        pendingAction={pendingActions[container.id]}
                      />
                      <ContainerDiagnosticsControls
                        align="end"
                        container={container}
                        onOpenLogs={onOpenLogs}
                        onOpenNetworkTest={onOpenNetworkTest}
                        rowBusy={rowBusy}
                      />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MobileContainerCards({
  containers,
  networkRates,
  pendingActions,
  onAction,
  onOpenLogs,
  onOpenNetworkTest,
}: {
  containers: ContainerSummary[];
  networkRates: NetworkRateMap;
  pendingActions: Record<string, ContainerAction>;
  onAction: (container: ContainerSummary, action: ContainerAction) => void;
  onOpenLogs: (container: ContainerSummary) => void;
  onOpenNetworkTest: (container: ContainerSummary) => void;
}) {
  return (
    <div className="grid gap-3 xl:hidden">
      {containers.map((container) => {
        const webPort = getContainerWebPort(container);
        const rowBusy = Boolean(pendingActions[container.id]);

        return (
          <Card key={container.id} className="overflow-hidden">
            <CardContent className="space-y-3 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{container.name}</p>
                  <p className="line-clamp-2 break-all text-xs text-muted-foreground">{container.image}</p>
                </div>
                <span
                  className={cn(
                    "shrink-0 rounded-full border px-2 py-1 text-xs font-medium capitalize",
                    getStatusTone(container.status),
                  )}
                >
                  {container.status}
                </span>
              </div>

              <div className="grid gap-2 text-xs sm:grid-cols-2">
                <div className="space-y-1 rounded-lg border border-border/70 bg-muted/30 p-2">
                  <p className="uppercase tracking-wide text-muted-foreground">CPU</p>
                  <MetricCell percent={container.cpu_percent} />
                </div>
                <div className="space-y-1 rounded-lg border border-border/70 bg-muted/30 p-2">
                  <p className="uppercase tracking-wide text-muted-foreground">Memory</p>
                  <MetricCell
                    detail={`${formatBytes(container.memory_used)} / ${formatBytes(container.memory_limit)}`}
                    percent={container.memory_percent}
                  />
                </div>
              </div>

              <div className="grid gap-1 rounded-lg border border-border/70 bg-muted/30 p-2 text-xs">
                <p className="uppercase tracking-wide text-muted-foreground">Network</p>
                <NetworkCell
                  rate={networkRates[container.id]}
                  rx={container.net_rx}
                  tx={container.net_tx}
                />
              </div>

              <div className="grid gap-2 sm:flex sm:items-center sm:justify-between">
                {webPort ? (
                  <a
                    aria-label={`Open ${container.name} web UI in a new tab`}
                    className="inline-flex min-h-11 items-center rounded-md border border-border px-3 text-sm text-primary underline-offset-2 hover:bg-muted hover:underline"
                    href={`http://${window.location.hostname}:${webPort}`}
                    rel="noopener noreferrer"
                    target="_blank"
                  >
                    Open Web UI
                  </a>
                ) : (
                  <span className="text-xs text-muted-foreground">Web UI unavailable</span>
                )}
              </div>

              <ContainerActionControls
                align="start"
                container={container}
                onAction={onAction}
                pendingAction={pendingActions[container.id]}
              />
              <ContainerDiagnosticsControls
                align="start"
                container={container}
                onOpenLogs={onOpenLogs}
                onOpenNetworkTest={onOpenNetworkTest}
                rowBusy={rowBusy}
              />
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

function ModalOverlay({
  onClose,
  children,
}: {
  onClose: () => void;
  children: ReactNode;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = containerRef.current;
    // Capture the control to restore focus to on close. Only treat focus that is
    // currently *outside* the dialog as the trigger, which guards against React 18
    // StrictMode's mount->unmount->mount double-invoke (where the re-mount would
    // otherwise capture an element inside the modal as the "trigger").
    const active = document.activeElement as HTMLElement | null;
    const triggerEl = node && active && !node.contains(active) ? active : null;

    const focusables = node
      ? Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
      : [];
    (focusables[0] ?? node)?.focus();

    // Lock body scroll while the dialog is open (prevents scroll-behind on mobile).
    const previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !node) {
        return;
      }
      const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (!items.length) {
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.body.style.overflow = previousBodyOverflow;
      triggerEl?.focus?.();
    };
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/75 p-3 sm:p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
      ref={containerRef}
      tabIndex={-1}
    >
      {children}
    </div>
  );
}

export function ContainersPage() {
  const [containers, setContainers] = useState<ContainerSummary[]>([]);
  const [networkRates, setNetworkRates] = useState<NetworkRateMap>({});
  const [filter, setFilter] = useState<ContainerFilter>("all");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState("Never");
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [pendingActions, setPendingActions] = useState<Record<string, ContainerAction>>({});
  const [logsModal, setLogsModal] = useState<LogsModalState>({
    open: false,
    status: "idle",
    containerId: null,
    containerName: "",
    logs: "",
    error: null,
  });
  const [containerNetworkModal, setContainerNetworkModal] = useState<ContainerNetworkModalState>({
    open: false,
    status: "idle",
    containerId: null,
    containerName: "",
    result: null,
    error: null,
  });
  const [hostNetworkPanel, setHostNetworkPanel] = useState<HostNetworkPanelState>({
    visible: false,
    status: "idle",
    result: null,
    error: null,
  });
  const isMountedRef = useRef(true);
  const pendingActionsRef = useRef<Record<string, ContainerAction>>({});
  const containersRef = useRef<ContainerSummary[]>([]);
  const previousNetworkStatsRef = useRef<Map<string, { rx: number; tx: number }>>(new Map());
  const lastStatsFetchRef = useRef<number | null>(null);
  const statsInFlightRef = useRef(false);

  const applyContainers = useCallback((next: ContainerSummary[]) => {
    containersRef.current = next;
    setContainers(next);
  }, []);

  const setPendingAction = useCallback((containerId: string, action: ContainerAction | null) => {
    setPendingActions((current) => {
      const next = { ...current };
      if (action) {
        next[containerId] = action;
      } else {
        delete next[containerId];
      }
      pendingActionsRef.current = next;
      return next;
    });
  }, []);

  const loadContainers = useCallback(
    async (reason: "initial" | "manual" | "poll" | "action"): Promise<ContainerSummary[] | null> => {
      if (reason === "initial") {
        setIsLoading(true);
      }
      if (reason === "manual") {
        setIsRefreshing(true);
      }

      try {
        // Baseline (structure) fetch only; metrics are owned by the stats poll so
        // structural refreshes never blank live telemetry between samples.
        const nextContainers = await fetchContainers({ includeStats: false });
        if (!isMountedRef.current) {
          return null;
        }
        const previousById = new Map(containersRef.current.map((item) => [item.id, item]));
        const merged = nextContainers.map((container) => {
          const previous = previousById.get(container.id);
          // Only carry live metrics forward for containers that are still running. A
          // running -> stopped transition must drop stale telemetry (the stats poll only
          // covers running containers), matching the legacy null-stats behavior.
          if (!previous || container.status !== "running") {
            return container;
          }
          return {
            ...container,
            cpu_percent: previous.cpu_percent,
            memory_percent: previous.memory_percent,
            memory_used: previous.memory_used,
            memory_limit: previous.memory_limit,
            net_rx: previous.net_rx,
            net_tx: previous.net_tx,
          };
        });
        applyContainers(merged);
        setError(null);
        setLastUpdated(formatClockTime(new Date()));
        return merged;
      } catch (caughtError) {
        if (!isMountedRef.current) {
          return null;
        }
        setError(getErrorMessage(caughtError));
        return null;
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
    },
    [applyContainers],
  );

  const pollStats = useCallback(
    async (sourceContainers: ContainerSummary[]) => {
      const runningIds = sourceContainers
        .filter((container) => container.status === "running")
        .map((container) => container.id);

      if (!runningIds.length || statsInFlightRef.current) {
        return;
      }

      statsInFlightRef.current = true;
      try {
        const stats = await fetchContainerStats(runningIds);
        if (!isMountedRef.current) {
          return;
        }

        const now = Date.now();
        const lastFetch = lastStatsFetchRef.current;
        const previousStats = previousNetworkStatsRef.current;
        const nextPreviousStats = new Map<string, { rx: number; tx: number }>();
        const nextRates: NetworkRateMap = {};

        for (const [id, summary] of Object.entries(stats)) {
          const rx = summary.net_rx;
          const tx = summary.net_tx;
          if (rx === null || tx === null) {
            continue;
          }

          const previous = previousStats.get(id);
          if (previous && lastFetch !== null) {
            const elapsedSeconds = (now - lastFetch) / 1000;
            if (elapsedSeconds > 0) {
              nextRates[id] = {
                rxRate: Math.max(0, (rx - previous.rx) / elapsedSeconds),
                txRate: Math.max(0, (tx - previous.tx) / elapsedSeconds),
              };
            }
          }
          nextPreviousStats.set(id, { rx, tx });
        }

        previousNetworkStatsRef.current = nextPreviousStats;
        lastStatsFetchRef.current = now;
        setNetworkRates(nextRates);

        const merged = containersRef.current.map((container) => {
          const summary = stats[container.id];
          if (!summary) {
            return container;
          }
          return {
            ...container,
            cpu_percent: summary.cpu_percent,
            memory_percent: summary.memory_percent,
            memory_used: summary.memory_used,
            memory_limit: summary.memory_limit,
            net_rx: summary.net_rx,
            net_tx: summary.net_tx,
          };
        });
        applyContainers(merged);
      } catch {
        // Stats are best-effort telemetry; keep last-known values like the legacy page.
      } finally {
        statsInFlightRef.current = false;
      }
    },
    [applyContainers],
  );

  const onContainerAction = useCallback(
    async (container: ContainerSummary, action: ContainerAction) => {
      if (pendingActionsRef.current[container.id]) {
        return;
      }

      const meta = ACTION_META[action];
      setPendingAction(container.id, action);
      setActionNotice({
        tone: "info",
        message: `${meta.pendingLabel.replace("...", "")} ${container.name}...`,
      });

      try {
        const result = await runContainerAction(container.id, action);
        if (isMountedRef.current) {
          setActionNotice({
            tone: "success",
            message: getActionSuccessMessage(container.name, action, result),
          });
        }
      } catch (caughtError) {
        if (isMountedRef.current) {
          setActionNotice({
            tone: "error",
            message: `${meta.label} failed for ${container.name}: ${getErrorMessage(caughtError)}`,
          });
        }
      } finally {
        const refreshed = await loadContainers("action");
        if (refreshed) {
          await pollStats(refreshed);
        }
        if (isMountedRef.current) {
          setPendingAction(container.id, null);
        }
      }
    },
    [loadContainers, pollStats, setPendingAction],
  );

  const closeLogsModal = useCallback(() => {
    setLogsModal((current) => ({ ...current, open: false }));
  }, []);

  const closeContainerNetworkModal = useCallback(() => {
    setContainerNetworkModal((current) => ({ ...current, open: false }));
  }, []);

  const onOpenLogs = useCallback(async (container: ContainerSummary) => {
    setLogsModal({
      open: true,
      status: "loading",
      containerId: container.id,
      containerName: container.name,
      logs: "",
      error: null,
    });

    try {
      const result = await fetchContainerLogs(container.id);
      if (!isMountedRef.current) {
        return;
      }
      setLogsModal({
        open: true,
        status: "ready",
        containerId: container.id,
        containerName: result.container || container.name,
        logs: result.logs || "No logs available.",
        error: null,
      });
    } catch (caughtError) {
      if (!isMountedRef.current) {
        return;
      }
      setLogsModal({
        open: true,
        status: "error",
        containerId: container.id,
        containerName: container.name,
        logs: "",
        error: getErrorMessage(caughtError),
      });
    }
  }, []);

  const onOpenContainerNetworkTest = useCallback(async (container: ContainerSummary) => {
    setContainerNetworkModal({
      open: true,
      status: "loading",
      containerId: container.id,
      containerName: container.name,
      result: null,
      error: null,
    });

    try {
      const result = await runContainerNetworkTest(container.id);
      if (!isMountedRef.current) {
        return;
      }
      setContainerNetworkModal({
        open: true,
        status: "ready",
        containerId: container.id,
        containerName: result.container_name || container.name,
        result,
        error: null,
      });
    } catch (caughtError) {
      if (!isMountedRef.current) {
        return;
      }
      setContainerNetworkModal({
        open: true,
        status: "error",
        containerId: container.id,
        containerName: container.name,
        result: null,
        error: getErrorMessage(caughtError),
      });
    }
  }, []);

  const runHostDiagnostics = useCallback(async () => {
    setHostNetworkPanel((current) => ({
      ...current,
      visible: true,
      status: "loading",
      result: null,
      error: null,
    }));

    try {
      const result = await runHostNetworkTest();
      if (!isMountedRef.current) {
        return;
      }
      setHostNetworkPanel({
        visible: true,
        status: "ready",
        result,
        error: null,
      });
    } catch (caughtError) {
      if (!isMountedRef.current) {
        return;
      }
      setHostNetworkPanel({
        visible: true,
        status: "error",
        result: null,
        error: getErrorMessage(caughtError),
      });
    }
  }, []);

  const refreshNow = useCallback(
    async (reason: "initial" | "manual" | "poll" | "action") => {
      const refreshed = await loadContainers(reason);
      if (refreshed) {
        await pollStats(refreshed);
      }
    },
    [loadContainers, pollStats],
  );

  useEffect(() => {
    isMountedRef.current = true;

    void refreshNow("initial");

    const intervalId = window.setInterval(() => {
      void refreshNow("poll");
    }, POLL_INTERVAL_MS);

    return () => {
      isMountedRef.current = false;
      window.clearInterval(intervalId);
    };
  }, [refreshNow]);

  useEffect(() => {
    if (!actionNotice || actionNotice.tone === "error") {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      setActionNotice(null);
    }, 4500);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [actionNotice]);

  const filteredContainers = useMemo(
    () => filterContainers(containers, filter),
    [containers, filter],
  );

  const hostNetworkStatus = getNetworkStatus(
    hostNetworkPanel.status,
    hostNetworkPanel.result ? hostNetworkPanel.result.ping_success : null,
  );
  const containerNetworkStatus = getNetworkStatus(
    containerNetworkModal.status,
    containerNetworkModal.result ? containerNetworkModal.result.ping_success : null,
  );

  return (
    <section className="space-y-4 sm:space-y-6">
      <Card>
        <CardHeader className="space-y-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0 space-y-1">
              <CardTitle className="flex items-center gap-2 text-lg sm:text-xl">
                <Server aria-hidden="true" className="h-5 w-5 text-primary" />
                Docker Containers
              </CardTitle>
              <CardDescription>
                Phase 2 pilot now serves live telemetry, lifecycle actions, and diagnostics on
                v2 containers.
              </CardDescription>
            </div>
            <span className="inline-flex min-h-11 items-center rounded-md border border-border bg-muted/70 px-3 text-xs text-muted-foreground">
              Last updated: {lastUpdated}
            </span>
          </div>

          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
            <div aria-label="Container filters" className="flex flex-wrap items-center gap-2" role="group">
              {FILTER_ITEMS.map((item) => (
                <Button
                  aria-pressed={filter === item.key}
                  key={item.key}
                  onClick={() => setFilter(item.key)}
                  variant={filter === item.key ? "default" : "outline"}
                >
                  {item.label}
                </Button>
              ))}
            </div>

            <div className="flex flex-wrap gap-2">
              <Button
                className="gap-2"
                id="v2-host-network-test-button"
                onClick={() => void runHostDiagnostics()}
                variant="outline"
              >
                {hostNetworkPanel.status === "loading" ? (
                  <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                ) : (
                  <Wifi aria-hidden="true" className="h-4 w-4" />
                )}
                Host Network Test
              </Button>
              <Button
                className="gap-2"
                disabled={isRefreshing}
                onClick={() => void refreshNow("manual")}
                variant="outline"
              >
                <RefreshCw
                  aria-hidden="true"
                  className={cn("h-4 w-4", isRefreshing ? "animate-spin" : "")}
                />
                {isRefreshing ? "Refreshing" : "Refresh"}
              </Button>
            </div>
          </div>
        </CardHeader>
      </Card>

      {hostNetworkPanel.visible ? (
        <Card className="border-sky-500/30" id="v2-host-network-panel">
          <CardHeader className="space-y-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <CardTitle className="text-base sm:text-lg">Host Network Diagnostics</CardTitle>
                <CardDescription>Runs a direct host probe against public network endpoints.</CardDescription>
              </div>
              <Button
                id="v2-host-network-hide"
                onClick={() => setHostNetworkPanel((current) => ({ ...current, visible: false }))}
                variant="outline"
              >
                Hide
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-2 rounded-lg border border-border/70 bg-muted/30 p-3 text-sm sm:grid-cols-3">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Status</p>
                <p className={cn("font-medium", hostNetworkStatus.className)} id="v2-host-network-status">
                  {hostNetworkStatus.label}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Local IP</p>
                <p className="break-words font-mono text-xs sm:text-sm">
                  {formatNetworkValue(hostNetworkPanel.result?.local_ip ?? null)}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Public IP</p>
                <p className="break-words font-mono text-xs sm:text-sm">
                  {formatNetworkValue(hostNetworkPanel.result?.public_ip ?? null)}
                </p>
              </div>
            </div>
            <div className="grid gap-2 rounded-lg border border-border/70 bg-muted/30 p-3 text-sm">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Probe Method</p>
              <p className="font-mono text-xs sm:text-sm">
                {formatNetworkValue(hostNetworkPanel.result?.probe_method ?? null)}
              </p>
            </div>
            <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
              <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">Output</p>
              <pre
                className="max-h-[16rem] overflow-auto whitespace-pre-wrap break-words text-xs sm:text-sm"
                id="v2-host-network-output"
              >
                {hostNetworkPanel.status === "loading"
                  ? "Running test..."
                  : hostNetworkPanel.status === "error"
                    ? hostNetworkPanel.error || "Host diagnostics failed"
                    : hostNetworkPanel.result?.ping_output || "No output provided."}
              </pre>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {actionNotice ? (
        <Card
          aria-live={actionNotice.tone === "error" ? "assertive" : "polite"}
          className={getNoticeToneClass(actionNotice.tone)}
          role="status"
        >
          <CardContent className="flex items-center gap-2 p-4 text-sm">
            {actionNotice.tone === "error" ? (
              <TriangleAlert aria-hidden="true" className="h-4 w-4" />
            ) : actionNotice.tone === "info" ? (
              <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
            ) : (
              <Activity aria-hidden="true" className="h-4 w-4" />
            )}
            {actionNotice.message}
          </CardContent>
        </Card>
      ) : null}

      {error && !containers.length ? (
        <Card className="border-rose-500/40">
          <CardContent className="flex flex-col items-start gap-3 p-4 sm:p-6">
            <div className="flex items-center gap-2 text-rose-300">
              <TriangleAlert aria-hidden="true" className="h-4 w-4" />
              <p className="text-sm font-medium">Unable to load containers</p>
            </div>
            <p className="text-sm text-muted-foreground">{error}</p>
            <Button onClick={() => void refreshNow("manual")} variant="outline">
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {error && containers.length ? (
        <Card className="border-amber-500/40">
          <CardContent className="flex items-center gap-2 p-4 text-sm text-amber-300">
            <TriangleAlert aria-hidden="true" className="h-4 w-4" />
            Refresh failed: {error}
          </CardContent>
        </Card>
      ) : null}

      {isLoading ? (
        <Card aria-live="polite" role="status">
          <CardContent className="flex min-h-[14rem] items-center justify-center gap-2 p-6 text-sm text-muted-foreground">
            <Activity aria-hidden="true" className="h-4 w-4 animate-pulse text-primary" />
            Loading containers...
          </CardContent>
        </Card>
      ) : null}

      {!isLoading && !filteredContainers.length ? (
        <Card>
          <CardContent className="flex min-h-[10rem] items-center justify-center p-6 text-sm text-muted-foreground">
            No {filter} containers found.
          </CardContent>
        </Card>
      ) : null}

      {!isLoading && filteredContainers.length ? (
        <>
          <DesktopContainerTable
            containers={filteredContainers}
            networkRates={networkRates}
            onAction={onContainerAction}
            onOpenLogs={onOpenLogs}
            onOpenNetworkTest={onOpenContainerNetworkTest}
            pendingActions={pendingActions}
          />
          <MobileContainerCards
            containers={filteredContainers}
            networkRates={networkRates}
            onAction={onContainerAction}
            onOpenLogs={onOpenLogs}
            onOpenNetworkTest={onOpenContainerNetworkTest}
            pendingActions={pendingActions}
          />
        </>
      ) : null}

      {logsModal.open ? (
        <ModalOverlay onClose={closeLogsModal}>
          <Card
            aria-labelledby="v2-logs-modal-title"
            aria-modal="true"
            className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden"
            id="v2-logs-modal"
            role="dialog"
          >
            <CardHeader className="flex flex-row items-start justify-between gap-3 border-b border-border/70 p-4 sm:p-5">
              <div className="space-y-1">
                <CardTitle id="v2-logs-modal-title" className="text-base sm:text-lg">
                  Container Logs: {logsModal.containerName}
                </CardTitle>
                <CardDescription>
                  Tail output from `/api/containers/&lt;id&gt;/logs`.
                </CardDescription>
              </div>
              <Button id="v2-logs-modal-close" onClick={closeLogsModal} variant="outline">
                Close
              </Button>
            </CardHeader>
            <CardContent className="p-0">
              <div className="max-h-[calc(90vh-6rem)] overflow-auto p-4">
                <pre
                  className="rounded-lg border border-border/70 bg-muted/25 p-3 whitespace-pre-wrap break-words text-xs sm:text-sm"
                  id="v2-logs-content"
                >
                  {logsModal.status === "loading"
                    ? "Loading logs..."
                    : logsModal.status === "error"
                      ? logsModal.error || "Failed to load logs"
                      : logsModal.logs || "No logs available."}
                </pre>
              </div>
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}

      {containerNetworkModal.open ? (
        <ModalOverlay onClose={closeContainerNetworkModal}>
          <Card
            aria-labelledby="v2-container-network-modal-title"
            aria-modal="true"
            className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden"
            id="v2-container-network-modal"
            role="dialog"
          >
            <CardHeader className="flex flex-row items-start justify-between gap-3 border-b border-border/70 p-4 sm:p-5">
              <div className="space-y-1">
                <CardTitle id="v2-container-network-modal-title" className="text-base sm:text-lg">
                  Container Network Test: {containerNetworkModal.containerName}
                </CardTitle>
                <CardDescription>
                  Probe result from `/api/containers/&lt;id&gt;/network-test`.
                </CardDescription>
              </div>
              <Button
                id="v2-container-network-modal-close"
                onClick={closeContainerNetworkModal}
                variant="outline"
              >
                Close
              </Button>
            </CardHeader>
            <CardContent className="space-y-3 overflow-auto p-4">
              <div className="grid gap-2 rounded-lg border border-border/70 bg-muted/30 p-3 text-sm sm:grid-cols-3">
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Status</p>
                  <p className={cn("font-medium", containerNetworkStatus.className)} id="v2-container-network-status">
                    {containerNetworkStatus.label}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Local IP</p>
                  <p className="break-words font-mono text-xs sm:text-sm">
                    {formatNetworkValue(containerNetworkModal.result?.local_ip ?? null)}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Public IP</p>
                  <p className="break-words font-mono text-xs sm:text-sm">
                    {formatNetworkValue(containerNetworkModal.result?.public_ip ?? null)}
                  </p>
                </div>
              </div>
              <div className="grid gap-2 rounded-lg border border-border/70 bg-muted/30 p-3 text-sm">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Probe Method</p>
                <p className="font-mono text-xs sm:text-sm">
                  {formatNetworkValue(containerNetworkModal.result?.probe_method ?? null)}
                </p>
              </div>
              <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
                <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">Output</p>
                <pre
                  className="max-h-[16rem] overflow-auto whitespace-pre-wrap break-words text-xs sm:text-sm"
                  id="v2-container-network-output"
                >
                  {containerNetworkModal.status === "loading"
                    ? "Collecting diagnostics..."
                    : containerNetworkModal.status === "error"
                      ? containerNetworkModal.error || "Failed to run container network test"
                      : containerNetworkModal.result?.ping_output || "No output provided."}
                </pre>
              </div>
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}
    </section>
  );
}
