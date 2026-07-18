import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  ExternalLink,
  FolderInput,
  HardDrive,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Thermometer,
  TriangleAlert,
  Unplug,
  X,
} from "lucide-react";

import { ActionMenu } from "@/components/ui/action-menu";
import { StatusBadge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MetricBar } from "@/components/ui/metric-bar";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import { PageHeader } from "@/components/ui/page-header";
import {
  type DiskInfo,
  type DiskSummary,
  type DiskSummaryDevice,
  type DiskUsage,
  type SmartHealth,
  type SmartTestType,
  type SuggestedMount,
  fetchDiskInventory,
  fetchDiskSmart,
  fetchHelperStatus,
  fetchSmartSummary,
  fetchSuggestedMounts,
  mountDisk,
  runSmartTest,
  unmountDisk,
} from "@/lib/disks";
import { mergeDiskSummaryHealth } from "@/lib/disk-summary";
import { formatBytes, formatClockTime } from "@/lib/format";
import { cn } from "@/lib/utils";

type AsyncStatus = "idle" | "loading" | "ready" | "error";

interface SmartModalState {
  open: boolean;
  status: AsyncStatus;
  device: string;
  result: SmartHealth | null;
  error: string | null;
}

interface ActionNotice {
  message: string;
  tone: "info" | "success" | "error";
}

function getNoticeToneClass(tone: ActionNotice["tone"]): string {
  if (tone === "success") {
    return "border-success/30 text-success";
  }
  if (tone === "error") {
    return "border-danger/30 text-danger";
  }
  return "border-info/30 text-info";
}

function getHealthTone(status: string): BadgeProps["tone"] {
  switch (status) {
    case "healthy":
      return "success";
    case "warning":
      return "warning";
    case "failing":
      return "danger";
    default:
      return "neutral";
  }
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "Unable to load disks";
}

function getUsageTone(percent: number): "success" | "warning" | "danger" {
  if (percent >= 90) return "danger";
  if (percent >= 75) return "warning";
  return "success";
}

function getDiskUsage(disk: DiskInfo): DiskUsage | null {
  if (disk.usage?.total !== null && disk.usage?.total !== undefined) {
    return disk.usage;
  }

  const mountedUsage = disk.partitions
    .map((partition) => partition.usage)
    .filter((usage): usage is DiskUsage => usage?.total !== null && usage?.total !== undefined);
  if (!mountedUsage.length) return null;

  const total = mountedUsage.reduce((sum, usage) => sum + (usage.total ?? 0), 0);
  const used = mountedUsage.reduce((sum, usage) => sum + (usage.used ?? 0), 0);
  const available = mountedUsage.reduce(
    (sum, usage) => sum + (usage.available ?? 0),
    0,
  );
  return {
    total,
    used,
    available,
    percent: total > 0 ? (used / total) * 100 : 0,
  };
}

function providerRoute(href: string): string {
  if (href.startsWith("/pools/") || href.startsWith("/protection/")) return "/pools";
  return href.startsWith("/") ? href : "/pools";
}

function DiskSummaryBand({ summary }: { summary: DiskSummary }) {
  const { counts, capacity } = summary;
  const healthDetail = [
    counts.warning ? `${counts.warning} warning` : "",
    counts.failing ? `${counts.failing} failing` : "",
    counts.unknown ? `${counts.unknown} unknown` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const allocationDetail =
    counts.assigned === null
      ? "Provider assignments unavailable"
      : `${counts.assigned} assigned · ${counts.unassigned ?? 0} unassigned`;

  return (
    <section
      aria-label="Disk summary"
      className="grid overflow-hidden rounded-md border border-border bg-card sm:grid-cols-2 xl:grid-cols-4"
      data-disk-summary
    >
      <div className="border-b border-border p-3 sm:border-r xl:border-b-0">
        <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-dim">Health</p>
        <p className="mt-1 text-sm font-medium">{counts.healthy} healthy</p>
        <p className={cn("mt-0.5 text-xs", healthDetail ? "text-warning" : "text-muted-foreground")}>
          {healthDetail || `${counts.total} devices reporting`}
        </p>
      </div>
      <div className="border-b border-border p-3 xl:border-b-0 xl:border-r">
        <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-dim">Mount state</p>
        <p className="mt-1 text-sm font-medium">{counts.mounted} mounted</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{counts.unmounted} unmounted</p>
      </div>
      <div className="border-b border-border p-3 sm:border-b-0 sm:border-r">
        <div className="flex items-baseline justify-between gap-2">
          <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-dim">Mounted capacity</p>
          <span className="font-mono text-[11px] text-muted-foreground">
            {capacity.mounted_percent === null ? "—" : `${Math.round(capacity.mounted_percent)}%`}
          </span>
        </div>
        <p className="mt-1 text-sm font-medium">{formatBytes(capacity.mounted_used_bytes)} used</p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {formatBytes(capacity.mounted_available_bytes)} free
        </p>
        {capacity.mounted_percent !== null ? (
          <MetricBar
            className="mt-2"
            label="Mounted disk capacity"
            tone={getUsageTone(capacity.mounted_percent)}
            value={capacity.mounted_percent}
          />
        ) : null}
      </div>
      <div className="p-3">
        <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-dim">Providers</p>
        <p className="mt-1 text-sm font-medium">
          {counts.assigned === null ? "Not checked" : `${counts.assigned} assigned`}
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {counts.unused === null ? allocationDetail : `${counts.unused} unused · ${allocationDetail}`}
        </p>
      </div>
    </section>
  );
}

function SmartDetailRow({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border/50 py-1.5 last:border-0">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="font-mono text-xs sm:text-sm">{value === null || value === "" ? "—" : value}</span>
    </div>
  );
}

function ConfirmButton({
  actionKey,
  label,
  confirmLabel = "Confirm",
  pendingLabel = "Working...",
  className,
  confirmKey,
  setConfirmKey,
  pendingKey,
  disabled,
  onConfirm,
  requestData,
  confirmData,
}: {
  actionKey: string;
  label: string;
  confirmLabel?: string;
  pendingLabel?: string;
  className?: string;
  confirmKey: string | null;
  setConfirmKey: (key: string | null) => void;
  pendingKey: string | null;
  disabled?: boolean;
  onConfirm: () => void;
  requestData?: Record<string, string>;
  confirmData?: Record<string, string>;
}) {
  if (pendingKey === actionKey) {
    return (
      <Button className={cn("gap-1.5 text-xs sm:text-sm", className)} disabled size="sm" variant="outline">
        <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
        {pendingLabel}
      </Button>
    );
  }
  if (confirmKey === actionKey) {
    return (
      <span className="flex items-center gap-1.5">
        <Button
          autoFocus
          className={cn("text-xs sm:text-sm", className)}
          onClick={onConfirm}
          size="sm"
          variant="outline"
          {...confirmData}
        >
          {confirmLabel}
        </Button>
        <Button onClick={() => setConfirmKey(null)} size="sm" variant="outline">
          Cancel
        </Button>
      </span>
    );
  }
  return (
    <Button
      className={cn("text-xs sm:text-sm", className)}
      disabled={disabled || Boolean(pendingKey)}
      onClick={() => setConfirmKey(actionKey)}
      size="sm"
      variant="outline"
      {...requestData}
    >
      {label}
    </Button>
  );
}

function DiskCard({
  disk,
  summary,
  smart,
  helperAvailable,
  pendingKey,
  confirmKey,
  setConfirmKey,
  onSmart,
  onUnmount,
}: {
  disk: DiskInfo;
  summary?: DiskSummaryDevice;
  smart?: SmartHealth;
  helperAvailable: boolean | null;
  pendingKey: string | null;
  confirmKey: string | null;
  setConfirmKey: (key: string | null) => void;
  onSmart: (disk: DiskInfo) => void;
  onUnmount: (mountpoint: string) => void;
}) {
  const usage = getDiskUsage(disk);
  const usagePercent = usage?.percent ?? null;
  const health = smart?.health_status ?? summary?.health ?? "unknown";
  const temperature = smart?.temperature_c ?? summary?.temperature_c ?? null;
  const unmountTargets = [
    ...(disk.mountpoint ? [disk.mountpoint] : []),
    ...disk.partitions.flatMap((partition) => (partition.mountpoint ? [partition.mountpoint] : [])),
  ];
  const confirmedUnmount = unmountTargets.find((mountpoint) => confirmKey === `unmount:${mountpoint}`);
  return (
    <Card className="transition-colors duration-200 hover:border-primary/25">
      <CardContent className="space-y-4 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-2.5">
            <HardDrive aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <div className="min-w-0">
              <p className="truncate font-mono text-sm font-semibold">{disk.path}</p>
              <p className="truncate text-xs text-muted-foreground">{disk.model || "Unknown model"}</p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <StatusBadge label={health} tone={getHealthTone(health)} />
            <Button
              aria-label={`SMART details for ${disk.path}`}
              className="h-9 min-h-9 w-9 px-0"
              data-disk={disk.name}
              data-disk-action="smart"
              disabled={helperAvailable === false}
              onClick={() => onSmart(disk)}
              size="sm"
              title={
                helperAvailable === false
                  ? "SMART helper unavailable"
                  : `SMART details for ${disk.path}`
              }
              variant="outline"
            >
              <ShieldCheck aria-hidden="true" className="h-4 w-4" />
            </Button>
            {unmountTargets.length && helperAvailable !== false ? (
              <ActionMenu
                disabled={Boolean(pendingKey)}
                items={unmountTargets.map((mountpoint) => ({
                  id: `unmount:${mountpoint}`,
                  label: `Unmount ${mountpoint}`,
                  Icon: Unplug,
                  onSelect: () => setConfirmKey(`unmount:${mountpoint}`),
                  tone: "danger" as const,
                  data: { "data-unmount": mountpoint },
                }))}
                label={`More actions for ${disk.path}`}
                pending={Boolean(pendingKey?.startsWith("unmount:"))}
                triggerData={{ "data-disk-menu": disk.name }}
              />
            ) : null}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-y border-border/70 py-2 font-mono text-xs text-muted-foreground">
          <span><span className="text-dim">Size </span>{disk.size || "—"}</span>
          <span><span className="text-dim">Bus </span>{[disk.transport, disk.type].filter(Boolean).join(" · ") || "—"}</span>
          {temperature !== null ? (
            <span className="inline-flex items-center gap-1">
              <Thermometer aria-hidden="true" className="h-3.5 w-3.5 text-dim" />
              {temperature} °C
            </span>
          ) : null}
        </div>

        {usage && usagePercent !== null ? (
          <div data-disk-usage={disk.name}>
            <div className="flex items-baseline justify-between gap-3">
              <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-dim">
                Mounted usage
              </p>
              <p className="font-mono text-xs text-muted-foreground">
                {Math.round(usagePercent)}% used
              </p>
            </div>
            <MetricBar
              className="mt-2"
              label={`${disk.path} mounted usage`}
              tone={getUsageTone(usagePercent)}
              value={usagePercent}
            />
            <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 font-mono text-[11px]">
              <span>
                <span className="text-dim">Used </span>
                {formatBytes(usage.used)}
              </span>
              <span>
                <span className="text-dim">Free </span>
                {formatBytes(usage.available)}
              </span>
            </div>
          </div>
        ) : null}

        {disk.partitions.length ? (
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-dim">Partitions</p>
            <div className="mt-1 divide-y divide-border/70 border-y border-border/70">
              {disk.partitions.map((part) => {
                const partPercent = part.usage?.percent ?? null;
                return (
                  <div className="space-y-1.5 py-2.5 text-xs" key={part.path}>
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="break-all font-mono font-medium">{part.path}</span>
                      {part.fstype ? (
                        <span className="rounded bg-info/10 px-1.5 py-0.5 font-mono text-info">{part.fstype}</span>
                      ) : null}
                      <span className="ml-auto font-mono text-muted-foreground">{part.size || "—"}</span>
                    </div>
                    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                      {part.mountpoint ? (
                        <span className="break-all font-mono text-success">{part.mountpoint}</span>
                      ) : (
                        <span className="text-muted-foreground">Unmounted</span>
                      )}
                      {part.usage && partPercent !== null ? (
                        <span className="font-mono text-[11px] text-muted-foreground">
                          {Math.round(partPercent)}% · {formatBytes(part.usage.used)} used · {formatBytes(part.usage.available)} free
                        </span>
                      ) : null}
                    </div>
                    {partPercent !== null ? (
                      <MetricBar
                        label={`${part.path} usage`}
                        tone={getUsageTone(partPercent)}
                        value={partPercent}
                      />
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}

        {summary?.assignments.length ? (
          <div className="flex flex-wrap items-center gap-2 border-t border-border/70 pt-3">
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-dim">Providers</span>
            {summary.assignments.map((assignment) => (
              <Link
                className="inline-flex min-h-8 items-center gap-1 rounded border border-border bg-muted/20 px-2 text-xs text-primary hover:border-primary/40 hover:bg-muted/40"
                key={`${assignment.provider_id}:${assignment.resource_id}:${assignment.device_path}`}
                to={providerRoute(assignment.href)}
              >
                <span>{assignment.resource_name || assignment.provider_id}</span>
                <span className="text-muted-foreground">· {assignment.role}</span>
                <ExternalLink aria-hidden="true" className="h-3 w-3" />
              </Link>
            ))}
          </div>
        ) : null}

        {confirmedUnmount ? (
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-danger/20 pt-3 text-xs text-danger">
            <span>Unmount {confirmedUnmount}?</span>
            <ConfirmButton
              actionKey={`unmount:${confirmedUnmount}`}
              className="border-danger/30 bg-danger/10 text-danger hover:bg-danger/15"
              confirmData={{ "data-confirm-unmount": confirmedUnmount }}
              confirmKey={confirmKey}
              confirmLabel="Confirm unmount"
              label="Unmount"
              onConfirm={() => onUnmount(confirmedUnmount)}
              pendingKey={pendingKey}
              pendingLabel="Unmounting..."
              setConfirmKey={setConfirmKey}
            />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function DisksPage() {
  const [disks, setDisks] = useState<DiskInfo[]>([]);
  const [helperAvailable, setHelperAvailable] = useState<boolean | null>(null);
  const [smart, setSmart] = useState<Record<string, SmartHealth>>({});
  const [diskSummary, setDiskSummary] = useState<DiskSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState("Never");
  const [smartModal, setSmartModal] = useState<SmartModalState>({
    open: false,
    status: "idle",
    device: "",
    result: null,
    error: null,
  });
  const [suggestions, setSuggestions] = useState<SuggestedMount[]>([]);
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [smartTestNotice, setSmartTestNotice] = useState<ActionNotice | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [confirmKey, setConfirmKey] = useState<string | null>(null);
  const isMountedRef = useRef(true);

  const loadAll = useCallback(async (reason: "initial" | "manual") => {
    if (reason === "initial") {
      setIsLoading(true);
    } else {
      setIsRefreshing(true);
    }

    // The inventory is the only thing on the critical path. SMART summary and the
    // helper-status probe can be slow (sleeping disks / USB enclosures), so they must
    // never gate the disk list — fetch them independently and merge once available.
    try {
      const inventory = await fetchDiskInventory();
      if (!isMountedRef.current) {
        return;
      }
      setDisks(inventory.disks);
      setDiskSummary(inventory.summary);
      setHelperAvailable(inventory.helper_available);
      setError(null);
      setLastUpdated(formatClockTime(new Date()));
    } catch (caughtError) {
      if (!isMountedRef.current) {
        return;
      }
      setError(getErrorMessage(caughtError));
    } finally {
      if (isMountedRef.current) {
        if (reason === "initial") {
          setIsLoading(false);
        } else {
          setIsRefreshing(false);
        }
      }
    }

    // Best-effort refinements, off the critical path.
    void fetchHelperStatus()
      .then((helper) => {
        if (isMountedRef.current) {
          setHelperAvailable(helper.available);
        }
      })
      .catch(() => {});
    void fetchSmartSummary()
      .then((summary) => {
        if (isMountedRef.current) {
          setSmart(summary);
        }
      })
      .catch(() => {});
    void fetchSuggestedMounts()
      .then((items) => {
        if (isMountedRef.current) {
          setSuggestions(items);
        }
      })
      .catch(() => {});
  }, []);

  const mergedSummary = useMemo(
    () => (diskSummary ? mergeDiskSummaryHealth(diskSummary, smart) : null),
    [diskSummary, smart],
  );

  const runDiskAction = useCallback(
    async (key: string, action: () => Promise<string>) => {
      if (pendingKey) {
        return;
      }
      setPendingKey(key);
      setConfirmKey(null);
      try {
        const message = await action();
        if (!isMountedRef.current) {
          return;
        }
        setActionNotice({ tone: "success", message });
        await loadAll("manual");
      } catch (caughtError) {
        if (isMountedRef.current) {
          setActionNotice({ tone: "error", message: getErrorMessage(caughtError) });
        }
      } finally {
        if (isMountedRef.current) {
          setPendingKey(null);
        }
      }
    },
    [loadAll, pendingKey],
  );

  const onMount = useCallback(
    (suggestion: SuggestedMount) =>
      runDiskAction(`mount:${suggestion.uuid}`, async () => {
        await mountDisk({
          uuid: suggestion.uuid,
          mountpoint: suggestion.suggested_mount,
          fstype: suggestion.fstype,
        });
        return `Mounted ${suggestion.device} at ${suggestion.suggested_mount}`;
      }),
    [runDiskAction],
  );

  const onUnmount = useCallback(
    (mountpoint: string) =>
      runDiskAction(`unmount:${mountpoint}`, async () => {
        const { warning } = await unmountDisk(mountpoint);
        return warning || `Unmounted ${mountpoint}`;
      }),
    [runDiskAction],
  );

  const onSmartTest = useCallback(
    async (deviceName: string, testType: SmartTestType) => {
      if (pendingKey) return;
      const key = `test:${deviceName}:${testType}`;
      setPendingKey(key);
      setConfirmKey(null);
      setSmartTestNotice(null);
      try {
        const message = await runSmartTest(deviceName, testType);
        if (isMountedRef.current) {
          setSmartTestNotice({ tone: "success", message });
        }
      } catch (caughtError) {
        if (isMountedRef.current) {
          setSmartTestNotice({ tone: "error", message: getErrorMessage(caughtError) });
        }
      } finally {
        if (isMountedRef.current) {
          setPendingKey(null);
        }
      }
    },
    [pendingKey],
  );

  const onSmart = useCallback(async (disk: DiskInfo) => {
    setSmartTestNotice(null);
    setSmartModal({ open: true, status: "loading", device: disk.path, result: null, error: null });
    try {
      const result = await fetchDiskSmart(disk.name);
      if (!isMountedRef.current) {
        return;
      }
      setSmart((current) => ({ ...current, [disk.path]: result }));
      setSmartModal({ open: true, status: "ready", device: disk.path, result, error: null });
    } catch (caughtError) {
      if (!isMountedRef.current) {
        return;
      }
      setSmartModal({ open: true, status: "error", device: disk.path, result: null, error: getErrorMessage(caughtError) });
    }
  }, []);

  const closeSmart = useCallback(() => {
    setSmartTestNotice(null);
    setConfirmKey(null);
    setSmartModal((current) => ({ ...current, open: false }));
  }, []);

  useEffect(() => {
    if (!actionNotice || actionNotice.tone === "error") return undefined;
    const timeoutId = window.setTimeout(() => setActionNotice(null), 4500);
    return () => window.clearTimeout(timeoutId);
  }, [actionNotice]);

  useEffect(() => {
    isMountedRef.current = true;
    void loadAll("initial");
    return () => {
      isMountedRef.current = false;
    };
  }, [loadAll]);

  return (
    <section className="space-y-4 sm:space-y-6">
      <PageHeader
        actions={
          <Button
            className="gap-2"
            disabled={isRefreshing}
            onClick={() => void loadAll("manual")}
            variant="secondary"
          >
            <RefreshCw aria-hidden="true" className={cn("h-4 w-4", isRefreshing ? "animate-spin" : "")} />
            {isRefreshing ? "refreshing" : "refresh"}
          </Button>
        }
        description={`${disks.length} devices · synced ${lastUpdated}`}
        status={
          <StatusBadge
            label={helperAvailable === false ? "limited" : "helper ready"}
            tone={helperAvailable === false ? "warning" : "success"}
          />
        }
        title="disk_management"
      />

      {helperAvailable === false ? (
        <Card aria-live="polite" className="border-warning/30" role="status">
          <CardContent className="flex items-center gap-2 p-4 text-sm text-warning">
            <TriangleAlert aria-hidden="true" className="h-4 w-4" />
            Privileged helper unavailable — disk and SMART operations are limited.
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
            ) : (
              <Activity aria-hidden="true" className="h-4 w-4" />
            )}
            <span>{actionNotice.message}</span>
            <Button
              aria-label="Dismiss disk notification"
              className="ml-auto h-8 min-h-8 w-8 px-0"
              onClick={() => setActionNotice(null)}
              size="sm"
              title="Dismiss"
              variant="ghost"
            >
              <X aria-hidden="true" className="h-4 w-4" />
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {error && disks.length ? (
        <div
          aria-live="polite"
          className="flex flex-wrap items-center gap-2 border-l-2 border-warning bg-warning/5 px-4 py-3 text-sm text-warning"
          role="status"
        >
          <TriangleAlert aria-hidden="true" className="h-4 w-4 shrink-0" />
          <span>Refresh failed. Showing data synced {lastUpdated}.</span>
          <span className="text-muted-foreground">{error}</span>
          <Button
            className="ml-auto gap-1.5"
            disabled={isRefreshing}
            onClick={() => void loadAll("manual")}
            size="sm"
            variant="outline"
          >
            <RefreshCw aria-hidden="true" className={cn("h-3.5 w-3.5", isRefreshing ? "animate-spin" : "")} />
            Retry
          </Button>
        </div>
      ) : null}

      {mergedSummary && disks.length ? <DiskSummaryBand summary={mergedSummary} /> : null}

      {suggestions.length && helperAvailable !== false ? (
        <section
          aria-label="Suggested mounts"
          className="border-y border-border bg-card/45 px-3 py-2.5 sm:px-4"
          id="v2-disk-suggestions"
        >
          <div className="flex flex-wrap items-center gap-2">
            <FolderInput aria-hidden="true" className="h-4 w-4 shrink-0 text-primary" />
            <p className="text-sm font-medium">
              {suggestions.length} suggested {suggestions.length === 1 ? "mount" : "mounts"}
            </p>
            <span className="text-xs text-muted-foreground">Unmounted filesystems detected</span>
          </div>
          <div className="mt-2 divide-y divide-border/70 border-t border-border/70">
            {suggestions.map((suggestion) => (
              <div
                className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-xs"
                key={suggestion.uuid}
              >
                <div className="min-w-0">
                  <p className="break-all font-mono text-sm">{suggestion.device}</p>
                  <p className="text-muted-foreground">
                    {suggestion.reason} → <span className="font-mono text-success">{suggestion.suggested_mount}</span>
                  </p>
                </div>
                <ConfirmButton
                  actionKey={`mount:${suggestion.uuid}`}
                  className="border-success/30 bg-success/10 text-success hover:bg-success/15"
                  confirmData={{ "data-confirm-mount": suggestion.uuid }}
                  confirmKey={confirmKey}
                  confirmLabel={`Mount at ${suggestion.suggested_mount}`}
                  label="Mount"
                  onConfirm={() => onMount(suggestion)}
                  pendingKey={pendingKey}
                  pendingLabel="Mounting..."
                  requestData={{ "data-mount": suggestion.uuid }}
                  setConfirmKey={setConfirmKey}
                />
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {error && !disks.length ? (
        <Card className="border-danger/30">
          <CardContent className="flex flex-col items-start gap-3 p-4 sm:p-6">
            <div className="flex items-center gap-2 text-danger">
              <TriangleAlert aria-hidden="true" className="h-4 w-4" />
              <p className="text-sm font-medium">Unable to load disks</p>
            </div>
            <p className="text-sm text-muted-foreground">{error}</p>
            <Button onClick={() => void loadAll("manual")} variant="outline">
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {isLoading ? (
        <Card aria-live="polite" role="status">
          <CardContent className="flex min-h-[14rem] items-center justify-center gap-2 p-6 text-sm text-muted-foreground">
            <Activity aria-hidden="true" className="h-4 w-4 animate-pulse text-primary" />
            Loading disks...
          </CardContent>
        </Card>
      ) : null}

      {!isLoading && !error && !disks.length && helperAvailable !== false ? (
        <Card>
          <CardContent className="flex min-h-[10rem] items-center justify-center p-6 text-sm text-muted-foreground">
            No disks found.
          </CardContent>
        </Card>
      ) : null}

      {!isLoading && disks.length ? (
        <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
          {disks.map((disk) => (
            <DiskCard
              confirmKey={confirmKey}
              disk={disk}
              helperAvailable={helperAvailable}
              key={disk.path}
              onSmart={onSmart}
              onUnmount={onUnmount}
              pendingKey={pendingKey}
              setConfirmKey={setConfirmKey}
              smart={smart[disk.path]}
              summary={mergedSummary?.devices.find((device) => device.path === disk.path)}
            />
          ))}
        </div>
      ) : null}

      {smartModal.open ? (
        <ModalOverlay onClose={closeSmart}>
          <Card
            aria-labelledby="v2-disk-smart-title"
            aria-modal="true"
            className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden"
            id="v2-disk-smart-modal"
            role="dialog"
          >
            <CardHeader className="flex flex-row items-start justify-between gap-3 border-b border-border/70 p-4 sm:p-5">
              <div>
                <CardTitle className="text-base sm:text-lg" id="v2-disk-smart-title">
                  SMART: {smartModal.device}
                </CardTitle>
              </div>
              <Button
                aria-label="Close SMART details"
                className="h-9 min-h-9 w-9 px-0"
                id="v2-disk-smart-close"
                onClick={closeSmart}
                size="sm"
                title="Close"
                variant="outline"
              >
                <X aria-hidden="true" className="h-4 w-4" />
              </Button>
            </CardHeader>
            <CardContent className="space-y-3 overflow-auto p-4" id="v2-disk-smart-content">
              {smartModal.status === "loading" ? (
                <p className="text-sm text-muted-foreground">Loading SMART data...</p>
              ) : smartModal.status === "error" ? (
                <div className="flex flex-wrap items-center gap-3 text-sm text-danger" role="alert">
                  <TriangleAlert aria-hidden="true" className="h-4 w-4" />
                  <span>{smartModal.error || "Failed to load SMART data"}</span>
                  <Button
                    aria-label="Retry SMART details"
                    className="ml-auto gap-1.5"
                    onClick={() => {
                      const disk = disks.find((item) => item.path === smartModal.device);
                      if (disk) void onSmart(disk);
                    }}
                    size="sm"
                    variant="outline"
                  >
                    <RefreshCw aria-hidden="true" className="h-3.5 w-3.5" />
                    Retry
                  </Button>
                </div>
              ) : smartModal.result ? (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge
                      label={smartModal.result.health_status}
                      tone={getHealthTone(smartModal.result.health_status)}
                    />
                    {smartModal.result.drive_type ? (
                      <span className="rounded bg-muted/50 px-2 py-1 text-xs uppercase">{smartModal.result.drive_type}</span>
                    ) : null}
                  </div>
                  {smartModal.result.error_message ? (
                    <p className="text-sm text-warning">{smartModal.result.error_message}</p>
                  ) : null}
                  <div className="rounded-lg border border-border/70 bg-muted/25 p-3">
                    <SmartDetailRow label="Model" value={smartModal.result.model} />
                    <SmartDetailRow label="Serial" value={smartModal.result.serial} />
                    <SmartDetailRow
                      label="Temperature"
                      value={smartModal.result.temperature_c === null ? null : `${smartModal.result.temperature_c} °C`}
                    />
                    <SmartDetailRow label="Power-on hours" value={smartModal.result.power_on_hours} />
                    <SmartDetailRow label="Reallocated sectors" value={smartModal.result.reallocated_sectors} />
                    <SmartDetailRow label="Pending sectors" value={smartModal.result.pending_sectors} />
                    <SmartDetailRow label="Uncorrectable errors" value={smartModal.result.uncorrectable_errors} />
                    <SmartDetailRow
                      label="Wear (used)"
                      value={smartModal.result.percentage_used === null ? null : `${smartModal.result.percentage_used}%`}
                    />
                    <SmartDetailRow
                      label="Available spare"
                      value={smartModal.result.available_spare === null ? null : `${smartModal.result.available_spare}%`}
                    />
                    <SmartDetailRow label="Media errors" value={smartModal.result.media_errors} />
                  </div>
                  {smartTestNotice ? (
                    <div
                      aria-live={smartTestNotice.tone === "error" ? "assertive" : "polite"}
                      className={cn(
                        "flex items-center gap-2 border-l-2 px-3 py-2 text-sm",
                        smartTestNotice.tone === "error"
                          ? "border-danger bg-danger/5 text-danger"
                          : "border-success bg-success/5 text-success",
                      )}
                      role="status"
                    >
                      {smartTestNotice.tone === "error" ? (
                        <TriangleAlert aria-hidden="true" className="h-4 w-4" />
                      ) : (
                        <Activity aria-hidden="true" className="h-4 w-4" />
                      )}
                      {smartTestNotice.message}
                    </div>
                  ) : null}
                  {helperAvailable !== false &&
                  smartModal.result.smart_available &&
                  smartModal.result.smart_enabled ? (
                    <div className="flex flex-wrap items-center gap-2" id="v2-disk-smart-test">
                      <span className="text-xs uppercase tracking-wide text-muted-foreground">Self-test</span>
                      {(["short", "long"] as SmartTestType[]).map((testType) => {
                        const deviceName = smartModal.device.replace(/^\/dev\//, "");
                        return (
                          <ConfirmButton
                            actionKey={`test:${deviceName}:${testType}`}
                            confirmData={{ "data-confirm-smarttest": testType }}
                            confirmKey={confirmKey}
                            confirmLabel={`Run ${testType} test`}
                            key={testType}
                            label={testType === "short" ? "Short" : "Long"}
                            onConfirm={() => onSmartTest(deviceName, testType)}
                            pendingKey={pendingKey}
                            pendingLabel="Starting..."
                            requestData={{ "data-smarttest": testType }}
                            setConfirmKey={setConfirmKey}
                          />
                        );
                      })}
                    </div>
                  ) : null}
                </>
              ) : (
                <p className="text-sm text-muted-foreground">No SMART data available.</p>
              )}
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}
    </section>
  );
}
