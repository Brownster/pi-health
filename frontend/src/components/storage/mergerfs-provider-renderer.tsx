import { useCallback, useEffect, useState } from "react";
import { FileText, RefreshCw, TriangleAlert } from "lucide-react";

import { CapabilityStatusPanel } from "@/components/capabilities/capability-status-panel";
import { CommandRunner } from "@/components/storage/command-runner";
import { MergerfsEditor } from "@/components/storage/mergerfs-editor";
import { PoolCapabilityCard } from "@/components/storage/pool-capability-card";
import { Button } from "@/components/ui/button";
import type { CapabilityStatus } from "@/lib/capabilities";
import type { PoolView } from "@/lib/pool-capabilities";
import {
  fetchPluginLatestLog,
  type PluginDetail,
} from "@/lib/storage-plugins";
import { cn } from "@/lib/utils";

type MergerfsTab = "overview" | "configuration" | "diagnostics";
type LogPhase = "idle" | "loading" | "ready" | "error";

function getErrorMessage(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : "Unable to load the latest provider log";
}

export function MergerfsProviderRenderer({
  detail,
  status,
  pools,
  canConfigure,
  onRefresh,
}: {
  detail: PluginDetail;
  status: CapabilityStatus;
  pools: PoolView[];
  canConfigure: boolean;
  onRefresh: () => Promise<void>;
}) {
  const [tab, setTab] = useState<MergerfsTab>(
    status.lifecycle.configured ? "overview" : canConfigure ? "configuration" : "overview",
  );
  const [logPhase, setLogPhase] = useState<LogPhase>("idle");
  const [latestLog, setLatestLog] = useState<string | null>(null);
  const [logError, setLogError] = useState("");
  const poolNames = pools.map((pool) => pool.name);
  const operationCommands = detail.commands.filter((command) =>
    ["mount", "unmount", "balance"].includes(command.id),
  );
  const diagnosticCommands = detail.commands.filter((command) => command.id === "status");
  const tabs: Array<{ id: MergerfsTab; label: string }> = [
    { id: "overview", label: "Overview" },
    ...(canConfigure ? [{ id: "configuration" as const, label: "Configuration" }] : []),
    { id: "diagnostics", label: "Diagnostics" },
  ];

  const loadLog = useCallback(async () => {
    setLogPhase("loading");
    setLogError("");
    try {
      setLatestLog(await fetchPluginLatestLog("mergerfs"));
      setLogPhase("ready");
    } catch (error) {
      setLogError(getErrorMessage(error));
      setLogPhase("error");
    }
  }, []);

  useEffect(() => {
    if (tab === "diagnostics" && logPhase === "idle") {
      void loadLog();
    }
  }, [loadLog, logPhase, tab]);

  return (
    <div className="space-y-5" data-capability-renderer="mergerfs">
      <div className="flex gap-1 overflow-x-auto border-b border-border" role="tablist" aria-label="MergerFS provider views">
        {tabs.map((item) => (
          <button
            aria-controls={`mergerfs-panel-${item.id}`}
            aria-selected={tab === item.id}
            className={cn(
              "min-h-11 shrink-0 border-b-2 px-3 font-mono text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              tab === item.id
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
            data-mergerfs-tab={item.id}
            id={`mergerfs-tab-${item.id}`}
            key={item.id}
            onClick={() => setTab(item.id)}
            role="tab"
            type="button"
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "overview" ? (
        <div aria-labelledby="mergerfs-tab-overview" className="space-y-5" id="mergerfs-panel-overview" role="tabpanel">
          <CapabilityStatusPanel status={status} />

          {pools.length ? (
            <section aria-labelledby="mergerfs-pools-title">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h2 className="font-mono text-sm font-semibold" id="mergerfs-pools-title">Configured pools</h2>
                <span className="text-xs text-dim">{pools.filter((pool) => pool.mounted).length}/{pools.length} mounted</span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {pools.map((pool) => <PoolCapabilityCard key={pool.id} pool={pool} />)}
              </div>
            </section>
          ) : (
            <div className="border-l-2 border-warning bg-warning/5 px-4 py-3 text-sm">
              <p className="font-medium text-warning">No pools configured</p>
              <p className="mt-1 text-muted-foreground">
                {canConfigure
                  ? "Open Configuration to add the first MergerFS pool."
                  : "An administrator must configure the first MergerFS pool."}
              </p>
            </div>
          )}

          {operationCommands.length ? (
            <section aria-labelledby="mergerfs-operations-title" className="border-t border-border pt-5">
              <h2 className="sr-only" id="mergerfs-operations-title">Pool operations</h2>
              {canConfigure ? (
                <CommandRunner
                  commands={operationCommands}
                  heading="Pool operations"
                  onCompleted={onRefresh}
                  pluginId="mergerfs"
                  poolNames={poolNames}
                />
              ) : (
                <p className="text-xs text-muted-foreground">Administrator access is required for mount, unmount, and balance operations.</p>
              )}
            </section>
          ) : null}
        </div>
      ) : null}

      {tab === "configuration" && canConfigure ? (
        <section aria-labelledby="mergerfs-tab-configuration" className="space-y-4" id="mergerfs-panel-configuration" role="tabpanel">
          <div>
            <h2 className="font-mono text-sm font-semibold">Pool configuration</h2>
            <p className="mt-1 text-xs text-muted-foreground">Order branches by priority, choose the create policy, preview the managed fstab section, then save and apply.</p>
          </div>
          <MergerfsEditor config={detail.config} onSaved={onRefresh} pluginId="mergerfs" />
        </section>
      ) : null}

      {tab === "diagnostics" ? (
        <div aria-labelledby="mergerfs-tab-diagnostics" className="space-y-5" id="mergerfs-panel-diagnostics" role="tabpanel">
          {diagnosticCommands.length ? (
            <CommandRunner
              commands={diagnosticCommands}
              heading="Live diagnostics"
              onCompleted={onRefresh}
              pluginId="mergerfs"
              poolNames={poolNames}
            />
          ) : null}

          <section aria-labelledby="mergerfs-log-title" className="overflow-hidden rounded-md border border-border">
            <div className="flex items-center justify-between gap-3 border-b border-border bg-muted/20 px-3 py-2">
              <h2 className="flex items-center gap-2 font-mono text-xs font-semibold" id="mergerfs-log-title"><FileText aria-hidden="true" className="h-3.5 w-3.5" />Latest provider log</h2>
              <Button aria-label="Reload provider log" disabled={logPhase === "loading"} onClick={() => void loadLog()} size="icon" title="Reload provider log" variant="ghost"><RefreshCw aria-hidden="true" className={cn("h-3.5 w-3.5", logPhase === "loading" && "animate-spin")} /></Button>
            </div>
            {logPhase === "error" ? <p className="flex items-center gap-2 p-3 text-xs text-danger"><TriangleAlert aria-hidden="true" className="h-4 w-4" />{logError}</p> : null}
            {logPhase === "ready" ? <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words p-3 text-xs text-muted-foreground" data-mergerfs-log>{latestLog || "No provider log is available."}</pre> : null}
            {logPhase === "loading" ? <p className="p-3 text-xs text-muted-foreground">Loading provider log...</p> : null}
          </section>
        </div>
      ) : null}
    </div>
  );
}
