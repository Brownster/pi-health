import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, HardDrive, RefreshCw, ShieldCheck, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import {
  type DiskInfo,
  type SmartHealth,
  fetchDiskInventory,
  fetchDiskSmart,
  fetchHelperStatus,
  fetchSmartSummary,
} from "@/lib/disks";
import { formatClockTime } from "@/lib/format";
import { cn } from "@/lib/utils";

type AsyncStatus = "idle" | "loading" | "ready" | "error";

interface SmartModalState {
  open: boolean;
  status: AsyncStatus;
  device: string;
  result: SmartHealth | null;
  error: string | null;
}

function getHealthTone(status: string): string {
  switch (status) {
    case "healthy":
      return "bg-emerald-500/15 text-emerald-300 border-emerald-500/40";
    case "warning":
      return "bg-amber-500/15 text-amber-300 border-amber-500/40";
    case "failing":
      return "bg-rose-500/15 text-rose-300 border-rose-500/40";
    default:
      return "bg-slate-500/15 text-slate-300 border-slate-500/40";
  }
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "Unable to load disks";
}

function SmartDetailRow({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border/50 py-1.5 last:border-0">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="font-mono text-xs sm:text-sm">{value === null || value === "" ? "—" : value}</span>
    </div>
  );
}

function DiskCard({
  disk,
  smart,
  onSmart,
}: {
  disk: DiskInfo;
  smart?: SmartHealth;
  onSmart: (disk: DiskInfo) => void;
}) {
  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate font-mono text-sm font-semibold">{disk.path}</p>
            <p className="truncate text-xs text-muted-foreground">{disk.model || "Unknown model"}</p>
          </div>
          {smart ? (
            <span
              className={cn(
                "shrink-0 rounded-full border px-2 py-1 text-xs font-medium capitalize",
                getHealthTone(smart.health_status),
              )}
            >
              {smart.health_status}
            </span>
          ) : null}
        </div>

        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-lg border border-border/70 bg-muted/30 p-2">
            <p className="uppercase tracking-wide text-muted-foreground">Size</p>
            <p className="font-mono">{disk.size || "—"}</p>
          </div>
          <div className="rounded-lg border border-border/70 bg-muted/30 p-2">
            <p className="uppercase tracking-wide text-muted-foreground">Bus</p>
            <p className="font-mono">{[disk.transport, disk.type].filter(Boolean).join(" · ") || "—"}</p>
          </div>
        </div>

        {disk.partitions.length ? (
          <div className="space-y-1.5">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Partitions</p>
            {disk.partitions.map((part) => (
              <div
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/70 bg-muted/20 p-2 text-xs"
                key={part.path}
              >
                <span className="break-all font-mono">{part.path}</span>
                <span className="flex flex-wrap items-center gap-2">
                  {part.fstype ? (
                    <span className="rounded bg-sky-500/10 px-1.5 py-0.5 font-mono text-sky-300">{part.fstype}</span>
                  ) : null}
                  {part.mountpoint ? (
                    <span className="font-mono text-emerald-300">{part.mountpoint}</span>
                  ) : (
                    <span className="text-muted-foreground">unmounted</span>
                  )}
                  {part.size ? <span className="font-mono text-muted-foreground">{part.size}</span> : null}
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
  }, []);

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
      <Card>
        <CardHeader className="space-y-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0 space-y-1">
              <CardTitle className="flex items-center gap-2 text-lg sm:text-xl">
                <HardDrive aria-hidden="true" className="h-5 w-5 text-primary" />
                Disks
              </CardTitle>
              <CardDescription>Block devices, partitions, and SMART health.</CardDescription>
            </div>
            <span className="inline-flex min-h-11 items-center rounded-md border border-border bg-muted/70 px-3 text-xs text-muted-foreground">
              Last updated: {lastUpdated}
            </span>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              className="gap-2"
              disabled={isRefreshing}
              onClick={() => void loadAll("manual")}
              variant="outline"
            >
              <RefreshCw aria-hidden="true" className={cn("h-4 w-4", isRefreshing ? "animate-spin" : "")} />
              {isRefreshing ? "Refreshing" : "Refresh"}
            </Button>
          </div>
        </CardHeader>
      </Card>

      {helperAvailable === false ? (
        <Card aria-live="polite" className="border-amber-500/40" role="status">
          <CardContent className="flex items-center gap-2 p-4 text-sm text-amber-300">
            <TriangleAlert aria-hidden="true" className="h-4 w-4" />
            Privileged helper unavailable — disk and SMART operations are limited.
          </CardContent>
        </Card>
      ) : null}

      {error && !disks.length ? (
        <Card className="border-rose-500/40">
          <CardContent className="flex flex-col items-start gap-3 p-4 sm:p-6">
            <div className="flex items-center gap-2 text-rose-300">
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
            <DiskCard disk={disk} key={disk.path} onSmart={onSmart} smart={smart[disk.path]} />
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
                <p className="text-sm text-rose-300">{smartModal.error || "Failed to load SMART data"}</p>
              ) : smartModal.result ? (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={cn(
                        "rounded-full border px-2 py-1 text-xs font-medium capitalize",
                        getHealthTone(smartModal.result.health_status),
                      )}
                    >
                      {smartModal.result.health_status}
                    </span>
                    {smartModal.result.drive_type ? (
                      <span className="rounded bg-muted/50 px-2 py-1 text-xs uppercase">{smartModal.result.drive_type}</span>
                    ) : null}
                  </div>
                  {smartModal.result.error_message ? (
                    <p className="text-sm text-amber-300">{smartModal.result.error_message}</p>
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
