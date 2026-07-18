import { useCallback, useEffect, useState } from "react";
import {
  FileText,
  HardDrive,
  RefreshCw,
  TriangleAlert,
} from "lucide-react";

import { CapabilityStatusPanel } from "@/components/capabilities/capability-status-panel";
import { CommandRunner } from "@/components/storage/command-runner";
import { ProtectionSetCard } from "@/components/storage/protection-set-card";
import { SnapraidEditor } from "@/components/storage/snapraid-editor";
import { Button } from "@/components/ui/button";
import type { CapabilityStatus } from "@/lib/capabilities";
import type { ProtectionSetView } from "@/lib/protection-capabilities";
import {
  fetchPluginLatestLog,
  fetchPluginRecovery,
  type PluginDetail,
} from "@/lib/storage-plugins";
import { cn } from "@/lib/utils";

type SnapraidTab = "overview" | "configuration" | "operations" | "recovery" | "diagnostics";
type LoadPhase = "idle" | "loading" | "ready" | "error";

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function SnapraidRecoveryStatus({ data }: { data: Record<string, unknown> | null }) {
  if (!data) {
    return <p className="text-sm text-muted-foreground">Recovery status is not available.</p>;
  }
  const failedDrives = Array.isArray(data.failed_drives)
    ? data.failed_drives.map((drive) => String(drive))
    : [];
  const options = Array.isArray(data.recovery_options)
    ? data.recovery_options.map((option) => record(option))
    : [];
  const error = data.error != null ? String(data.error) : "";
  return (
    <div className="space-y-4" data-snapraid-recovery-status>
      {error ? <p className="flex items-start gap-2 border-l-2 border-danger bg-danger/5 px-3 py-2.5 text-sm text-danger"><TriangleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />{error}</p> : null}
      <dl className="grid grid-cols-3 overflow-hidden rounded-md border border-border">
        {[
          {
            label: "Recoverable",
            value: data.recoverable === true ? "Yes" : data.recoverable === false ? "No" : "Unknown",
          },
          { label: "Missing files", value: String(data.missing_files ?? 0) },
          { label: "Damaged files", value: String(data.damaged_files ?? 0) },
        ].map((item) => <div className="border-r border-border p-3 last:border-r-0" key={item.label}><dt className="font-mono text-[9px] uppercase text-dim">{item.label}</dt><dd className="mt-1 text-sm font-semibold tabular-nums">{item.value}</dd></div>)}
      </dl>
      {failedDrives.length ? <section aria-labelledby="snapraid-failed-drives"><h3 className="flex items-center gap-2 font-mono text-xs font-semibold" id="snapraid-failed-drives"><HardDrive aria-hidden="true" className="h-3.5 w-3.5 text-danger" />Failed drives</h3><ul className="mt-2 divide-y divide-border rounded-md border border-border">{failedDrives.map((drive) => <li className="px-3 py-2 font-mono text-xs" key={drive}>{drive}</li>)}</ul></section> : null}
      {options.length ? <section aria-labelledby="snapraid-recovery-options"><h3 className="font-mono text-xs font-semibold" id="snapraid-recovery-options">Recovery options</h3><ul className="mt-2 divide-y divide-border rounded-md border border-border">{options.map((option, index) => <li className="px-3 py-2 text-xs" key={String(option.id ?? index)}><p className="font-medium">{String(option.name ?? option.id ?? "Recovery option")}</p><p className="mt-0.5 font-mono text-[10px] text-muted-foreground">{String(option.command ?? "fix")}</p></li>)}</ul></section> : null}
    </div>
  );
}

export function SnapraidProviderRenderer({
  detail,
  status,
  protectionSets,
  canConfigure,
  onRefresh,
}: {
  detail: PluginDetail;
  status: CapabilityStatus;
  protectionSets: ProtectionSetView[];
  canConfigure: boolean;
  onRefresh: () => Promise<void>;
}) {
  const [tab, setTab] = useState<SnapraidTab>(
    status.lifecycle.configured ? "overview" : canConfigure ? "configuration" : "overview",
  );
  const [recoveryPhase, setRecoveryPhase] = useState<LoadPhase>("idle");
  const [recovery, setRecovery] = useState<Record<string, unknown> | null>(null);
  const [recoveryError, setRecoveryError] = useState("");
  const [logPhase, setLogPhase] = useState<LoadPhase>("idle");
  const [latestLog, setLatestLog] = useState<string | null>(null);
  const [logError, setLogError] = useState("");
  const operations = detail.commands
    .filter((command) => ["sync", "scrub"].includes(command.id))
    .map((command) => command.id === "sync" ? { ...command, dangerous: true } : command);
  const diagnostics = detail.commands.filter((command) => ["status", "diff", "check"].includes(command.id));
  const fixes = detail.commands.filter((command) => command.id === "fix");
  const tabs: Array<{ id: SnapraidTab; label: string }> = [
    { id: "overview", label: "Overview" },
    ...(canConfigure ? [{ id: "configuration" as const, label: "Configuration" }] : []),
    ...(canConfigure && operations.length ? [{ id: "operations" as const, label: "Operations" }] : []),
    { id: "recovery", label: "Recovery" },
    { id: "diagnostics", label: "Diagnostics" },
  ];

  const loadRecovery = useCallback(async () => {
    setRecoveryPhase("loading");
    setRecoveryError("");
    try {
      const result = await fetchPluginRecovery("snapraid");
      setRecovery(result.supported ? result.data : null);
      setRecoveryPhase("ready");
    } catch (error) {
      setRecoveryError(getErrorMessage(error, "Unable to load recovery status"));
      setRecoveryPhase("error");
    }
  }, []);

  const loadLog = useCallback(async () => {
    setLogPhase("loading");
    setLogError("");
    try {
      setLatestLog(await fetchPluginLatestLog("snapraid"));
      setLogPhase("ready");
    } catch (error) {
      setLogError(getErrorMessage(error, "Unable to load the latest SnapRAID log"));
      setLogPhase("error");
    }
  }, []);

  useEffect(() => {
    if (tab === "recovery" && recoveryPhase === "idle") void loadRecovery();
    if (tab === "diagnostics" && logPhase === "idle") void loadLog();
  }, [loadLog, loadRecovery, logPhase, recoveryPhase, tab]);

  return (
    <div className="space-y-5" data-capability-renderer="snapraid">
      <div className="flex gap-1 overflow-x-auto border-b border-border" role="tablist" aria-label="SnapRAID provider views">
        {tabs.map((item) => <button aria-controls={`snapraid-panel-${item.id}`} aria-selected={tab === item.id} className={cn("min-h-11 shrink-0 border-b-2 px-3 font-mono text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", tab === item.id ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground")} data-snapraid-tab={item.id} id={`snapraid-tab-${item.id}`} key={item.id} onClick={() => setTab(item.id)} role="tab" type="button">{item.label}</button>)}
      </div>

      {tab === "overview" ? <div aria-labelledby="snapraid-tab-overview" className="space-y-5" id="snapraid-panel-overview" role="tabpanel"><CapabilityStatusPanel status={status} />{protectionSets.length ? <section aria-labelledby="snapraid-protection-title"><h2 className="mb-3 font-mono text-sm font-semibold" id="snapraid-protection-title">Protection sets</h2><div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{protectionSets.map((item) => <ProtectionSetCard key={item.id} protectionSet={item} />)}</div></section> : <div className="border-l-2 border-warning bg-warning/5 px-4 py-3 text-sm"><p className="font-medium text-warning">No protection set configured</p><p className="mt-1 text-muted-foreground">{canConfigure ? "Open Configuration to assign data and parity drives." : "An administrator must configure SnapRAID."}</p></div>}</div> : null}

      {tab === "configuration" && canConfigure ? <section aria-labelledby="snapraid-tab-configuration" className="space-y-4" id="snapraid-panel-configuration" role="tabpanel"><div><h2 className="font-mono text-sm font-semibold">Drive assignments and schedule</h2><p className="mt-1 text-xs text-muted-foreground">Assign mounted disks, set scrub policy and schedules, preview snapraid.conf, then save and apply.</p></div><SnapraidEditor config={detail.config} onSaved={onRefresh} pluginId="snapraid" /></section> : null}

      {tab === "operations" && canConfigure ? <section aria-labelledby="snapraid-tab-operations" className="space-y-4" id="snapraid-panel-operations" role="tabpanel"><div><h2 className="font-mono text-sm font-semibold">Parity operations</h2><p className="mt-1 text-xs text-muted-foreground">Sync updates parity. Scrub verifies a bounded percentage of protected data.</p></div><CommandRunner commands={operations} heading="Run operation" onCompleted={onRefresh} pluginId="snapraid" poolNames={[]} /></section> : null}

      {tab === "recovery" ? <section aria-labelledby="snapraid-tab-recovery" className="space-y-5" id="snapraid-panel-recovery" role="tabpanel"><div className="flex items-center justify-between gap-3"><div><h2 className="font-mono text-sm font-semibold">Recovery status</h2><p className="mt-1 text-xs text-muted-foreground">Review array damage before running a parity fix.</p></div><Button aria-label="Reload recovery status" disabled={recoveryPhase === "loading"} onClick={() => void loadRecovery()} size="icon" title="Reload recovery status" variant="ghost"><RefreshCw aria-hidden="true" className={cn("h-4 w-4", recoveryPhase === "loading" && "animate-spin")} /></Button></div>{recoveryPhase === "loading" ? <p className="text-sm text-muted-foreground">Loading recovery status...</p> : null}{recoveryPhase === "error" ? <p className="flex items-start gap-2 text-sm text-danger"><TriangleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />{recoveryError}</p> : null}{recoveryPhase === "ready" ? <SnapraidRecoveryStatus data={recovery} /> : null}{canConfigure && fixes.length ? <div className="border-t border-border pt-5"><CommandRunner commands={fixes} heading="Recovery operation" onCompleted={onRefresh} pluginId="snapraid" poolNames={[]} /></div> : null}</section> : null}

      {tab === "diagnostics" ? <section aria-labelledby="snapraid-tab-diagnostics" className="space-y-5" id="snapraid-panel-diagnostics" role="tabpanel">{diagnostics.length ? <CommandRunner commands={diagnostics} heading="Live diagnostics" onCompleted={onRefresh} pluginId="snapraid" poolNames={[]} /> : null}<section aria-labelledby="snapraid-log-title" className="overflow-hidden rounded-md border border-border"><div className="flex items-center justify-between gap-3 border-b border-border bg-muted/20 px-3 py-2"><h2 className="flex items-center gap-2 font-mono text-xs font-semibold" id="snapraid-log-title"><FileText aria-hidden="true" className="h-3.5 w-3.5" />Latest operation log</h2><Button aria-label="Reload SnapRAID log" disabled={logPhase === "loading"} onClick={() => void loadLog()} size="icon" title="Reload SnapRAID log" variant="ghost"><RefreshCw aria-hidden="true" className={cn("h-3.5 w-3.5", logPhase === "loading" && "animate-spin")} /></Button></div>{logPhase === "error" ? <p className="flex items-center gap-2 p-3 text-xs text-danger"><TriangleAlert aria-hidden="true" className="h-4 w-4" />{logError}</p> : null}{logPhase === "ready" ? <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words p-3 text-xs text-muted-foreground" data-snapraid-log>{latestLog || "No operation log is available."}</pre> : null}{logPhase === "loading" ? <p className="p-3 text-xs text-muted-foreground">Loading operation log...</p> : null}</section></section> : null}
    </div>
  );
}
