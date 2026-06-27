import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Loader2, RefreshCw, TriangleAlert, Wifi } from "lucide-react";

import { Badge, StatusBadge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { type HostNetworkTestResult, runHostNetworkTest } from "@/lib/containers";
import {
  type NetworkGroup,
  fetchNetworkGroups,
  fetchTailscaleStatus,
  recreateNetworkGroup,
  tailscaleLogout,
} from "@/lib/network";
import { formatClockTime } from "@/lib/format";
import { cn } from "@/lib/utils";

interface ActionNotice {
  message: string;
  tone: "success" | "error";
}

type AsyncStatus = "idle" | "loading" | "ready" | "error";

function getErrorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : "Unable to complete the request";
}

function groupTone(status: string): BadgeProps["tone"] {
  return status === "ok" ? "success" : "warning";
}

export function NetworkPage() {
  const [groups, setGroups] = useState<NetworkGroup[]>([]);
  const [dockerAvailable, setDockerAvailable] = useState(true);
  const [tailscaleAvailable, setTailscaleAvailable] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState("Never");
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [confirmKey, setConfirmKey] = useState<string | null>(null);
  const [hostTest, setHostTest] = useState<{ status: AsyncStatus; result: HostNetworkTestResult | null; error: string | null }>({
    status: "idle",
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
    try {
      const [groupsResult, tailscale] = await Promise.all([
        fetchNetworkGroups(),
        fetchTailscaleStatus().catch(() => ({ available: false, data: null })),
      ]);
      if (!isMountedRef.current) {
        return;
      }
      setGroups(groupsResult.groups);
      setDockerAvailable(groupsResult.docker_available);
      setTailscaleAvailable(tailscale.available);
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
        } else {
          setIsRefreshing(false);
        }
      }
    }
  }, []);

  const runAction = useCallback(
    async (key: string, action: () => Promise<void>, successMessage: string) => {
      if (pendingKey) {
        return;
      }
      setPendingKey(key);
      setConfirmKey(null);
      try {
        await action();
        if (isMountedRef.current) {
          setActionNotice({ tone: "success", message: successMessage });
          await loadAll("manual");
        }
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

  const onRunHostTest = useCallback(async () => {
    setHostTest({ status: "loading", result: null, error: null });
    try {
      const result = await runHostNetworkTest();
      if (isMountedRef.current) {
        setHostTest({ status: "ready", result, error: null });
      }
    } catch (caughtError) {
      if (isMountedRef.current) {
        setHostTest({ status: "error", result: null, error: getErrorMessage(caughtError) });
      }
    }
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
          <Button className="gap-2" disabled={isRefreshing} onClick={() => void loadAll("manual")} variant="secondary">
            <RefreshCw aria-hidden="true" className={cn("h-4 w-4", isRefreshing ? "animate-spin" : "")} />
            {isRefreshing ? "refreshing" : "refresh"}
          </Button>
        }
        description={`synced ${lastUpdated}`}
        title="network"
      />

      {actionNotice ? (
        <Card
          aria-live={actionNotice.tone === "error" ? "assertive" : "polite"}
          className={actionNotice.tone === "error" ? "border-danger/30 text-danger" : "border-success/30 text-success"}
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

      {isLoading ? (
        <Card aria-live="polite" role="status">
          <CardContent className="flex min-h-[14rem] items-center justify-center p-6 text-sm text-muted-foreground">
            Loading network...
          </CardContent>
        </Card>
      ) : (
        <>
          <Card id="v2-host-network-test">
            <CardHeader className="flex flex-row items-start justify-between gap-3">
              <div className="space-y-1">
                <CardTitle className="text-base sm:text-lg">Host network test</CardTitle>
                <CardDescription>Probe public connectivity from the host.</CardDescription>
              </div>
              <Button
                className="gap-2"
                disabled={hostTest.status === "loading"}
                id="v2-host-network-run"
                onClick={() => void onRunHostTest()}
                size="sm"
                variant="outline"
              >
                {hostTest.status === "loading" ? (
                  <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                ) : (
                  <Wifi aria-hidden="true" className="h-4 w-4" />
                )}
                Run test
              </Button>
            </CardHeader>
            {hostTest.status !== "idle" ? (
              <CardContent className="space-y-2 text-sm" id="v2-host-network-result">
                {hostTest.status === "error" ? (
                  <p className="text-danger">{hostTest.error}</p>
                ) : hostTest.status === "loading" ? (
                  <p className="text-muted-foreground">Running...</p>
                ) : hostTest.result ? (
                  <>
                    <StatusBadge
                      label={hostTest.result.ping_success ? "reachable" : "unreachable"}
                      tone={hostTest.result.ping_success ? "success" : "danger"}
                    />
                    <p className="font-mono text-xs text-muted-foreground">
                      local {hostTest.result.local_ip || "—"} · public {hostTest.result.public_ip || "—"}
                    </p>
                    {hostTest.result.ping_output ? (
                      <pre className="max-h-[16vh] overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-muted/25 p-3 text-xs">
                        {hostTest.result.ping_output}
                      </pre>
                    ) : null}
                  </>
                ) : null}
              </CardContent>
            ) : null}
          </Card>

          <Card id="v2-network-groups">
            <CardHeader>
              <CardTitle className="text-base sm:text-lg">VPN network groups</CardTitle>
              <CardDescription>Containers sharing a provider namespace (e.g. gluetun).</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {!dockerAvailable ? (
                <p className="text-sm text-muted-foreground">Docker unavailable.</p>
              ) : !groups.length ? (
                <p className="text-sm text-muted-foreground">No VPN network groups detected.</p>
              ) : (
                groups.map((group) => {
                  const recreateKey = `recreate:${group.provider}`;
                  return (
                    <div
                      className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-muted/20 p-3 text-xs"
                      key={group.provider}
                    >
                      <div className="min-w-0">
                        <p className="break-all font-mono text-sm">{group.provider}</p>
                        <p className="text-muted-foreground">
                          {group.member_count} members
                          {group.orphaned_members.length ? ` · ${group.orphaned_members.length} orphaned` : ""}
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge label={group.status} tone={groupTone(group.status)} />
                        {confirmKey === recreateKey ? (
                          <span className="flex items-center gap-1.5">
                            <Button
                              className="border-warning/30 bg-warning/10 text-warning hover:bg-warning/15 text-xs sm:text-sm"
                              data-confirm-recreate={group.provider}
                              onClick={() =>
                                void runAction(
                                  recreateKey,
                                  () => recreateNetworkGroup(group.provider),
                                  `Recreated ${group.provider} group`,
                                )
                              }
                              size="sm"
                              variant="outline"
                            >
                              Confirm recreate
                            </Button>
                            <Button onClick={() => setConfirmKey(null)} size="sm" variant="outline">
                              Cancel
                            </Button>
                          </span>
                        ) : (
                          <Button
                            className="text-xs sm:text-sm"
                            data-recreate={group.provider}
                            disabled={Boolean(pendingKey)}
                            onClick={() => setConfirmKey(recreateKey)}
                            size="sm"
                            variant="outline"
                          >
                            {pendingKey === recreateKey ? (
                              <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
                            ) : null}
                            Recreate
                          </Button>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </CardContent>
          </Card>

          <Card id="v2-tailscale">
            <CardHeader className="flex flex-row items-start justify-between gap-3">
              <div className="space-y-1">
                <CardTitle className="text-base sm:text-lg">Tailscale</CardTitle>
                <CardDescription>Mesh VPN status.</CardDescription>
              </div>
              <Badge tone={tailscaleAvailable ? "success" : "neutral"}>
                {tailscaleAvailable ? "connected" : "unavailable"}
              </Badge>
            </CardHeader>
            {tailscaleAvailable ? (
              <CardContent>
                {confirmKey === "tailscale-logout" ? (
                  <span className="flex items-center gap-1.5">
                    <Button
                      className="border-danger/30 bg-danger/10 text-danger hover:bg-danger/15"
                      id="v2-tailscale-logout-confirm"
                      onClick={() => void runAction("tailscale-logout", () => tailscaleLogout(), "Tailscale logged out")}
                      variant="outline"
                    >
                      Confirm logout
                    </Button>
                    <Button onClick={() => setConfirmKey(null)} variant="outline">
                      Cancel
                    </Button>
                  </span>
                ) : (
                  <Button
                    disabled={Boolean(pendingKey)}
                    id="v2-tailscale-logout"
                    onClick={() => setConfirmKey("tailscale-logout")}
                    variant="outline"
                  >
                    Log out
                  </Button>
                )}
              </CardContent>
            ) : null}
          </Card>
        </>
      )}
    </section>
  );
}
