import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Loader2,
  RefreshCw,
  TriangleAlert,
  Wifi,
} from "lucide-react";

import { StatusBadge } from "@/components/ui/badge";
import { ContainerDetail } from "@/components/containers/container-detail";
import { LogViewerModal } from "@/components/log-viewer-modal";
import {
  ACTION_META,
  ContainerList,
  type NetworkRateMap,
} from "@/components/containers/container-list";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import { PageHeader } from "@/components/ui/page-header";
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
  runContainerAction,
  runContainerNetworkTest,
  runHostNetworkTest,
} from "@/lib/containers";
import { formatClockTime } from "@/lib/format";
import { fetchNetworkGroups, recreateNetworkGroup, type NetworkGroup } from "@/lib/network";
import type { VpnRoleMap } from "@/components/containers/container-list";
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 10_000;
const GROUP_BY_STACK_KEY = "pihealth.containers.groupByStack";
const FILTER_ITEMS: Array<{ key: ContainerFilter; label: string }> = [
  { key: "all", label: "All" },
  { key: "running", label: "Running" },
  { key: "stopped", label: "Stopped" },
];
type AsyncStatus = "idle" | "loading" | "ready" | "error";

type ActionNotice = {
  message: string;
  tone: "info" | "success" | "error";
};

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

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "Unable to load containers";
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

  const suffix =
    action === "start"
      ? "started"
      : action === "stop"
        ? "stopped"
        : "restarted";
  return result.status || `${containerName} ${suffix} successfully`;
}

function formatNetworkValue(value: string | null): string {
  return value && value.trim().length > 0 ? value : "Unavailable";
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

export function ContainersPage() {
  const [containers, setContainers] = useState<ContainerSummary[]>([]);
  const [networkRates, setNetworkRates] = useState<NetworkRateMap>({});
  const [filter, setFilter] = useState<ContainerFilter>("all");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState("Never");
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [pendingActions, setPendingActions] = useState<
    Record<string, ContainerAction>
  >({});
  const [logsTarget, setLogsTarget] = useState<ContainerSummary | null>(null);
  const [detailTarget, setDetailTarget] = useState<ContainerSummary | null>(null);
  const [networkGroups, setNetworkGroups] = useState<NetworkGroup[]>([]);
  const [groupByStack, setGroupByStack] = useState<boolean>(() => {
    if (typeof localStorage === "undefined") return false;
    return localStorage.getItem(GROUP_BY_STACK_KEY) === "true";
  });
  const [containerNetworkModal, setContainerNetworkModal] =
    useState<ContainerNetworkModalState>({
      open: false,
      status: "idle",
      containerId: null,
      containerName: "",
      result: null,
      error: null,
    });
  const [hostNetworkPanel, setHostNetworkPanel] =
    useState<HostNetworkPanelState>({
      visible: false,
      status: "idle",
      result: null,
      error: null,
    });
  const isMountedRef = useRef(true);
  const pendingActionsRef = useRef<Record<string, ContainerAction>>({});
  const containersRef = useRef<ContainerSummary[]>([]);
  const vpnRolesRef = useRef<VpnRoleMap>({});
  const [providerUpdate, setProviderUpdate] = useState<ContainerSummary | null>(null);
  const [checkAll, setCheckAll] = useState<{ done: number; total: number } | null>(null);
  const previousNetworkStatsRef = useRef<
    Map<string, { rx: number; tx: number }>
  >(new Map());
  const lastStatsFetchRef = useRef<number | null>(null);
  const statsInFlightRef = useRef(false);

  const applyContainers = useCallback((next: ContainerSummary[]) => {
    containersRef.current = next;
    setContainers(next);
  }, []);

  const setPendingAction = useCallback(
    (containerId: string, action: ContainerAction | null) => {
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
    },
    [],
  );

  const loadContainers = useCallback(
    async (
      reason: "initial" | "manual" | "poll" | "action",
    ): Promise<ContainerSummary[] | null> => {
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
        const previousById = new Map(
          containersRef.current.map((item) => [item.id, item]),
        );
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

      // Updating a VPN network provider orphans its members' netns; gate behind an
      // explicit confirm that offers to recreate the group afterwards (PH5-006).
      if (action === "update" && vpnRolesRef.current[container.name]?.kind === "provider") {
        setProviderUpdate(container);
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

  const runProviderUpdate = useCallback(
    async (container: ContainerSummary, recreate: boolean) => {
      setProviderUpdate(null);
      setPendingAction(container.id, "update");
      setActionNotice({ tone: "info", message: `Updating ${container.name}...` });
      try {
        await runContainerAction(container.id, "update");
        if (recreate) {
          await recreateNetworkGroup(container.name);
        }
        if (isMountedRef.current) {
          setActionNotice({
            tone: "success",
            message: recreate
              ? `Updated ${container.name} and recreated its network group`
              : `Updated ${container.name} (members may need a manual group recreate)`,
          });
        }
      } catch (caughtError) {
        if (isMountedRef.current) {
          setActionNotice({
            tone: "error",
            message: `Provider update failed for ${container.name}: ${getErrorMessage(caughtError)}`,
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

  const checkAllUpdates = useCallback(async () => {
    const targets = containersRef.current.filter(
      (container) => container.status === "running",
    );
    if (!targets.length) {
      setActionNotice({ tone: "info", message: "No running containers to check." });
      return;
    }
    setCheckAll({ done: 0, total: targets.length });
    const updatable: string[] = [];
    let index = 0;
    let done = 0;
    // Bounded concurrency — each check pulls remote image metadata.
    const worker = async () => {
      while (index < targets.length) {
        const container = targets[index++];
        try {
          const result = await runContainerAction(container.id, "check_update");
          if (result.update_available) updatable.push(container.name);
        } catch {
          /* skip individual failures; the summary reflects what we could check */
        }
        done += 1;
        if (isMountedRef.current) setCheckAll({ done, total: targets.length });
      }
    };
    await Promise.all([worker(), worker(), worker()]);
    if (isMountedRef.current) {
      setCheckAll(null);
      setActionNotice({
        tone: updatable.length ? "info" : "success",
        message: updatable.length
          ? `Updates available (${updatable.length}): ${updatable.join(", ")}`
          : "All running containers are up to date.",
      });
      const refreshed = await loadContainers("action");
      if (refreshed) await pollStats(refreshed);
    }
  }, [loadContainers, pollStats]);

  const closeLogsModal = useCallback(() => {
    setLogsTarget(null);
  }, []);

  const closeContainerNetworkModal = useCallback(() => {
    setContainerNetworkModal((current) => ({ ...current, open: false }));
  }, []);

  const onOpenLogs = useCallback((container: ContainerSummary) => {
    setLogsTarget(container);
  }, []);

  const onOpenContainerNetworkTest = useCallback(
    async (container: ContainerSummary) => {
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
    },
    [],
  );

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

  // Network groups drive the VPN provider/member/orphaned badges. Fetched once; refreshed
  // alongside manual refreshes is unnecessary — group topology changes rarely.
  useEffect(() => {
    const controller = new AbortController();
    fetchNetworkGroups(controller.signal)
      .then((result) => setNetworkGroups(result.groups))
      .catch(() => {
        /* network groups are best-effort; absence just hides the badges */
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(GROUP_BY_STACK_KEY, groupByStack ? "true" : "false");
    }
  }, [groupByStack]);

  const vpnRoles = useMemo<VpnRoleMap>(() => {
    const map: VpnRoleMap = {};
    for (const group of networkGroups) {
      if (group.provider) map[group.provider] = { kind: "provider", provider: group.provider };
      for (const member of group.members) {
        map[member] = { kind: "member", provider: group.provider };
      }
      for (const orphan of group.orphaned_members) {
        map[orphan] = { kind: "orphaned", provider: group.provider };
      }
    }
    return map;
  }, [networkGroups]);

  useEffect(() => {
    vpnRolesRef.current = vpnRoles;
  }, [vpnRoles]);

  const containerGroups = useMemo(() => {
    if (!groupByStack) return null;
    const groups = new Map<string, ContainerSummary[]>();
    for (const container of filteredContainers) {
      const key = container.stack ?? "Standalone";
      const list = groups.get(key) ?? [];
      list.push(container);
      groups.set(key, list);
    }
    // Named stacks first (alpha), Standalone last.
    return [...groups.entries()].sort(([a], [b]) => {
      if (a === "Standalone") return 1;
      if (b === "Standalone") return -1;
      return a.localeCompare(b);
    });
  }, [groupByStack, filteredContainers]);

  const hostNetworkStatus = getNetworkStatus(
    hostNetworkPanel.status,
    hostNetworkPanel.result ? hostNetworkPanel.result.ping_success : null,
  );
  const containerNetworkStatus = getNetworkStatus(
    containerNetworkModal.status,
    containerNetworkModal.result
      ? containerNetworkModal.result.ping_success
      : null,
  );

  return (
    <section className="space-y-4 sm:space-y-6">
      <PageHeader
        actions={
          <>
            <Button
              className="gap-2"
              data-check-all-updates
              disabled={checkAll !== null}
              onClick={() => void checkAllUpdates()}
              variant="secondary"
            >
              <RefreshCw
                aria-hidden="true"
                className={cn("h-4 w-4", checkAll !== null ? "animate-spin" : "")}
              />
              {checkAll !== null ? `checking ${checkAll.done}/${checkAll.total}` : "check all"}
            </Button>
            <Button
              className="gap-2"
              id="v2-host-network-test-button"
              onClick={() => void runHostDiagnostics()}
              variant="secondary"
            >
              {hostNetworkPanel.status === "loading" ? (
                <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
              ) : (
                <Wifi aria-hidden="true" className="h-4 w-4" />
              )}
              network test
            </Button>
            <Button
              className="gap-2"
              disabled={isRefreshing}
              onClick={() => void refreshNow("manual")}
              variant="secondary"
            >
              <RefreshCw
                aria-hidden="true"
                className={cn("h-4 w-4", isRefreshing ? "animate-spin" : "")}
              />
              {isRefreshing ? "refreshing" : "refresh"}
            </Button>
          </>
        }
        description={`docker · ${containers.length} containers · synced ${lastUpdated}`}
        status={
          <StatusBadge
            label={`${containers.filter((container) => container.status === "running").length} running`}
            tone="success"
          />
        }
        title="docker_containers"
      />

      <div
        aria-label="Container filters"
        className="flex flex-wrap items-center gap-2"
        role="group"
      >
        {FILTER_ITEMS.map((item) => (
          <Button
            aria-pressed={filter === item.key}
            key={item.key}
            onClick={() => setFilter(item.key)}
            size="sm"
            variant={filter === item.key ? "default" : "outline"}
          >
            {item.label}
          </Button>
        ))}
        {containers.some((container) => container.update_available) ? (
          <Button
            aria-pressed={filter === "updates"}
            data-filter="updates"
            onClick={() => setFilter("updates")}
            size="sm"
            variant={filter === "updates" ? "default" : "outline"}
          >
            Updates ({containers.filter((container) => container.update_available).length})
          </Button>
        ) : null}
        <Button
          aria-pressed={groupByStack}
          className="ml-auto"
          data-group-by-stack
          onClick={() => setGroupByStack((value) => !value)}
          size="sm"
          variant={groupByStack ? "default" : "outline"}
        >
          Group by stack
        </Button>
      </div>

      {hostNetworkPanel.visible ? (
        <Card className="border-sky-500/30" id="v2-host-network-panel">
          <CardHeader className="space-y-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <CardTitle className="text-base sm:text-lg">
                  Host Network Diagnostics
                </CardTitle>
                <CardDescription>
                  Runs a direct host probe against public network endpoints.
                </CardDescription>
              </div>
              <Button
                id="v2-host-network-hide"
                onClick={() =>
                  setHostNetworkPanel((current) => ({
                    ...current,
                    visible: false,
                  }))
                }
                variant="outline"
              >
                Hide
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-2 rounded-lg border border-border/70 bg-muted/30 p-3 text-sm sm:grid-cols-3">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">
                  Status
                </p>
                <p
                  className={cn("font-medium", hostNetworkStatus.className)}
                  id="v2-host-network-status"
                >
                  {hostNetworkStatus.label}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">
                  Local IP
                </p>
                <p className="break-words font-mono text-xs sm:text-sm">
                  {formatNetworkValue(
                    hostNetworkPanel.result?.local_ip ?? null,
                  )}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">
                  Public IP
                </p>
                <p className="break-words font-mono text-xs sm:text-sm">
                  {formatNetworkValue(
                    hostNetworkPanel.result?.public_ip ?? null,
                  )}
                </p>
              </div>
            </div>
            <div className="grid gap-2 rounded-lg border border-border/70 bg-muted/30 p-3 text-sm">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">
                Probe Method
              </p>
              <p className="font-mono text-xs sm:text-sm">
                {formatNetworkValue(
                  hostNetworkPanel.result?.probe_method ?? null,
                )}
              </p>
            </div>
            <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
              <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
                Output
              </p>
              <pre
                className="max-h-[16rem] overflow-auto whitespace-pre-wrap break-words text-xs sm:text-sm"
                id="v2-host-network-output"
              >
                {hostNetworkPanel.status === "loading"
                  ? "Running test..."
                  : hostNetworkPanel.status === "error"
                    ? hostNetworkPanel.error || "Host diagnostics failed"
                    : hostNetworkPanel.result?.ping_output ||
                      "No output provided."}
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
            <Activity
              aria-hidden="true"
              className="h-4 w-4 animate-pulse text-primary"
            />
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
        containerGroups ? (
          <div className="space-y-6">
            {containerGroups.map(([stackName, groupContainers]) => (
              <section className="space-y-2" data-stack-group={stackName} key={stackName}>
                <div className="flex items-center gap-2">
                  {stackName === "Standalone" ? (
                    <h3 className="text-sm font-semibold text-muted-foreground">Standalone</h3>
                  ) : (
                    <a
                      className="text-sm font-semibold text-primary hover:underline"
                      href="/v2/stacks"
                    >
                      {stackName}
                    </a>
                  )}
                  <span className="text-xs text-muted-foreground">
                    {groupContainers.length}
                  </span>
                </div>
                <ContainerList
                  containers={groupContainers}
                  networkRates={networkRates}
                  onAction={onContainerAction}
                  onOpenDetails={setDetailTarget}
                  onOpenLogs={onOpenLogs}
                  onOpenNetworkTest={onOpenContainerNetworkTest}
                  pendingActions={pendingActions}
                  vpnRoles={vpnRoles}
                />
              </section>
            ))}
          </div>
        ) : (
          <ContainerList
            containers={filteredContainers}
            networkRates={networkRates}
            onAction={onContainerAction}
            onOpenDetails={setDetailTarget}
            onOpenLogs={onOpenLogs}
            onOpenNetworkTest={onOpenContainerNetworkTest}
            pendingActions={pendingActions}
            vpnRoles={vpnRoles}
          />
        )
      ) : null}

      {logsTarget ? (
        <LogViewerModal
          closeId="v2-logs-modal-close"
          description="Container log snapshot with optional five-second refresh."
          filename={`${logsTarget.name}.log`}
          idPrefix="v2-logs"
          load={async (tail) => (await fetchContainerLogs(logsTarget.id, tail)).logs}
          onClose={closeLogsModal}
          title={`Container Logs: ${logsTarget.name}`}
        />
      ) : null}

      {detailTarget ? (
        <ContainerDetail container={detailTarget} onClose={() => setDetailTarget(null)} />
      ) : null}

      {providerUpdate ? (
        <ModalOverlay onClose={() => setProviderUpdate(null)}>
          <Card className="w-full max-w-md" data-provider-update-modal>
            <CardHeader>
              <CardTitle className="text-base">Update {providerUpdate.name}?</CardTitle>
              <CardDescription>
                {providerUpdate.name} is a VPN network provider. Updating it recreates its
                container and orphans every member routed through it (
                <span className="font-mono">network_mode: service:</span>) until the group is
                recreated.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              <Button
                data-provider-update-recreate
                onClick={() => void runProviderUpdate(providerUpdate, true)}
              >
                Update & recreate group
              </Button>
              <Button
                onClick={() => void runProviderUpdate(providerUpdate, false)}
                variant="outline"
              >
                Update only
              </Button>
              <Button onClick={() => setProviderUpdate(null)} variant="ghost">
                Cancel
              </Button>
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
                <CardTitle
                  id="v2-container-network-modal-title"
                  className="text-base sm:text-lg"
                >
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
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">
                    Status
                  </p>
                  <p
                    className={cn(
                      "font-medium",
                      containerNetworkStatus.className,
                    )}
                    id="v2-container-network-status"
                  >
                    {containerNetworkStatus.label}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">
                    Local IP
                  </p>
                  <p className="break-words font-mono text-xs sm:text-sm">
                    {formatNetworkValue(
                      containerNetworkModal.result?.local_ip ?? null,
                    )}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">
                    Public IP
                  </p>
                  <p className="break-words font-mono text-xs sm:text-sm">
                    {formatNetworkValue(
                      containerNetworkModal.result?.public_ip ?? null,
                    )}
                  </p>
                </div>
              </div>
              <div className="grid gap-2 rounded-lg border border-border/70 bg-muted/30 p-3 text-sm">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">
                  Probe Method
                </p>
                <p className="font-mono text-xs sm:text-sm">
                  {formatNetworkValue(
                    containerNetworkModal.result?.probe_method ?? null,
                  )}
                </p>
              </div>
              <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
                <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
                  Output
                </p>
                <pre
                  className="max-h-[16rem] overflow-auto whitespace-pre-wrap break-words text-xs sm:text-sm"
                  id="v2-container-network-output"
                >
                  {containerNetworkModal.status === "loading"
                    ? "Collecting diagnostics..."
                    : containerNetworkModal.status === "error"
                      ? containerNetworkModal.error ||
                        "Failed to run container network test"
                      : containerNetworkModal.result?.ping_output ||
                        "No output provided."}
                </pre>
              </div>
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}
    </section>
  );
}
