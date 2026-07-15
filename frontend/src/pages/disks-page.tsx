import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Loader2, RefreshCw, ShieldCheck, TriangleAlert } from "lucide-react";

import { StatusBadge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { MetricBar } from "@/components/ui/metric-bar";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import { PageHeader } from "@/components/ui/page-header";
import {
  type DiskInfo,
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
  smart,
  helperAvailable,
  pendingKey,
  confirmKey,
  setConfirmKey,
  onSmart,
  onUnmount,
}: {
  disk: DiskInfo;
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
  return (
    <Card className="transition-colors duration-200 hover:border-primary/25">
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate font-mono text-sm font-semibold">{disk.path}</p>
            <p className="truncate text-xs text-muted-foreground">{disk.model || "Unknown model"}</p>
          </div>
          {smart ? (
            <StatusBadge
              className="shrink-0"
              label={smart.health_status}
              tone={getHealthTone(smart.health_status)}
            />
          ) : null}
        </div>

        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-md border border-border bg-muted/20 p-2">
            <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-dim">Size</p>
            <p className="font-mono">{disk.size || "—"}</p>
          </div>
          <div className="rounded-md border border-border bg-muted/20 p-2">
            <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-dim">Bus</p>
            <p className="font-mono">{[disk.transport, disk.type].filter(Boolean).join(" · ") || "—"}</p>
          </div>
        </div>

        {usage && usagePercent !== null ? (
          <div className="rounded-md border border-border bg-muted/20 p-2" data-disk-usage={disk.name}>
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
          <div className="space-y-1.5">
            <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-dim">Partitions</p>
            {disk.partitions.map((part) => (
              <div
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-muted/20 p-2 text-xs"
                key={part.path}
              >
                <span className="break-all font-mono">{part.path}</span>
                <span className="flex flex-wrap items-center gap-2">
                  {part.fstype ? (
                    <span className="rounded bg-info/10 px-1.5 py-0.5 font-mono text-info">{part.fstype}</span>
                  ) : null}
                  {part.mountpoint ? (
                    <span className="font-mono text-success">{part.mountpoint}</span>
                  ) : (
                    <span className="text-muted-foreground">unmounted</span>
                  )}
                  {part.size ? <span className="font-mono text-muted-foreground">{part.size}</span> : null}
                  {part.mountpoint && helperAvailable !== false ? (
                    <ConfirmButton
                      actionKey={`unmount:${part.mountpoint}`}
                      className="border-danger/30 bg-danger/10 text-danger hover:bg-danger/15"
                      confirmData={{ "data-confirm-unmount": part.mountpoint }}
                      confirmKey={confirmKey}
                      confirmLabel="Confirm unmount"
                      label="Unmount"
                      onConfirm={() => onUnmount(part.mountpoint as string)}
                      pendingKey={pendingKey}
                      pendingLabel="Unmounting..."
                      requestData={{ "data-unmount": part.mountpoint }}
                      setConfirmKey={setConfirmKey}
                    />
                  ) : null}
                </span>
              </div>
            ))}
          </div>
        ) : null}

        <div className="flex flex-wrap gap-2">
          <Button
            aria-label={`SMART details for ${disk.path}`}
            className="gap-1.5 text-xs sm:text-sm"
            data-disk={disk.name}
            data-disk-action="smart"
            onClick={() => onSmart(disk)}
            size="sm"
            variant="outline"
          >
            <ShieldCheck aria-hidden="true" className="h-3.5 w-3.5" />
            SMART
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function DisksPage() {
  const [disks, setDisks] = useState<DiskInfo[]>([]);
  const [helperAvailable, setHelperAvailable] = useState<boolean | null>(null);
  const [smart, setSmart] = useState<Record<string, SmartHealth>>({});
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
    (deviceName: string, testType: SmartTestType) =>
      runDiskAction(`test:${deviceName}:${testType}`, () => runSmartTest(deviceName, testType)),
    [runDiskAction],
  );

  const onSmart = useCallback(async (disk: DiskInfo) => {
    setSmartModal({ open: true, status: "loading", device: disk.path, result: null, error: null });
    try {
      const result = await fetchDiskSmart(disk.name);
      if (!isMountedRef.current) {
        return;
      }
      setSmartModal({ open: true, status: "ready", device: disk.path, result, error: null });
    } catch (caughtError) {
      if (!isMountedRef.current) {
        return;
      }
      setSmartModal({ open: true, status: "error", device: disk.path, result: null, error: getErrorMessage(caughtError) });
    }
  }, []);

  const closeSmart = useCallback(() => {
    setSmartModal((current) => ({ ...current, open: false }));
  }, []);

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
            {actionNotice.message}
          </CardContent>
        </Card>
      ) : null}

      {suggestions.length && helperAvailable !== false ? (
        <Card id="v2-disk-suggestions">
          <CardHeader>
            <CardTitle className="text-base sm:text-lg">Suggested mounts</CardTitle>
            <CardDescription>Unmounted partitions detected with a recommended mount point.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {suggestions.map((suggestion) => (
              <div
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-muted/20 p-3 text-xs"
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
          </CardContent>
        </Card>
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
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
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
              <div className="space-y-1">
                <CardTitle className="text-base sm:text-lg" id="v2-disk-smart-title">
                  SMART: {smartModal.device}
                </CardTitle>
                <CardDescription>Health detail from `/api/disks/&lt;device&gt;/smart`.</CardDescription>
              </div>
              <Button id="v2-disk-smart-close" onClick={closeSmart} variant="outline">
                Close
              </Button>
            </CardHeader>
            <CardContent className="space-y-3 overflow-auto p-4" id="v2-disk-smart-content">
              {smartModal.status === "loading" ? (
                <p className="text-sm text-muted-foreground">Loading SMART data...</p>
              ) : smartModal.status === "error" ? (
                <p className="text-sm text-danger">{smartModal.error || "Failed to load SMART data"}</p>
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
                  {helperAvailable !== false ? (
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
