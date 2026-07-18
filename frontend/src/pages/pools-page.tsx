import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Boxes,
  CircleAlert,
  Database,
  Plus,
  RefreshCw,
  Settings2,
  TriangleAlert,
} from "lucide-react";
import { Link, useParams } from "react-router-dom";

import {
  APP_PATHS,
  extensionDetailsPath,
  poolProviderPath,
} from "@/app/route-contract";
import { useAuth } from "@/components/auth/auth-provider";
import { GenericCapabilityRenderer } from "@/components/capabilities/generic-capability-renderer";
import { MergerfsProviderRenderer } from "@/components/storage/mergerfs-provider-renderer";
import { PoolCapabilityCard } from "@/components/storage/pool-capability-card";
import { StatusBadge, type BadgeProps } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { fetchCapability, type CapabilityDescriptor, type CapabilityHealthState } from "@/lib/capabilities";
import { formatBytes, formatClockTime } from "@/lib/format";
import {
  adaptLegacyPoolingProviders,
  enrichPoolingCapability,
  poolCapabilityView,
  type PoolProviderView,
} from "@/lib/pool-capabilities";
import { fetchPluginDetail, fetchPlugins, type PluginDetail } from "@/lib/storage-plugins";
import { cn } from "@/lib/utils";

type LoadPhase = "loading" | "ready" | "error";

function getErrorMessage(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : "Unable to load pooling providers";
}

function healthTone(state: CapabilityHealthState): BadgeProps["tone"] {
  if (state === "healthy") return "success";
  if (state === "warning" || state === "unconfigured") return "warning";
  if (["error", "unavailable", "incompatible"].includes(state)) return "danger";
  return "neutral";
}

function PoolSummary({ view }: { view: ReturnType<typeof poolCapabilityView> }) {
  const { summary } = view;
  const cells = [
    { label: "Pools", value: String(summary.totalPools), detail: `${view.enabledProviders.length} enabled provider${view.enabledProviders.length === 1 ? "" : "s"}` },
    { label: "Mounted", value: `${summary.mountedPools}/${summary.totalPools}`, detail: !summary.totalPools ? "No pools configured" : summary.mountedPools !== summary.totalPools ? "Mount state needs attention" : "All configured pools available" },
    { label: "Capacity", value: formatBytes(summary.totalBytes) ?? "Not reported", detail: `${formatBytes(summary.freeBytes) ?? "Unknown"} free` },
    { label: "Warnings", value: String(summary.warnings), detail: summary.warnings ? "Review provider health" : "No provider warnings" },
  ];
  return (
    <dl aria-label="Pool summary" className="grid grid-cols-2 overflow-hidden rounded-md border border-border bg-card xl:grid-cols-4" data-pool-summary>
      {cells.map((cell) => (
        <div className="min-w-0 border-b border-border p-4 odd:border-r [&:nth-last-child(-n+2)]:border-b-0 xl:border-b-0 xl:border-r xl:last:border-r-0" key={cell.label}>
          <dt className="font-mono text-[10px] uppercase text-dim">{cell.label}</dt>
          <dd className="mt-1 text-lg font-semibold tabular-nums text-foreground">{cell.value}</dd>
          <p className="mt-1 truncate text-xs text-muted-foreground" title={cell.detail}>{cell.detail}</p>
        </div>
      ))}
    </dl>
  );
}

function ProviderRow({ provider, actionLabel = "Set up" }: { provider: PoolProviderView; actionLabel?: string }) {
  return (
    <div className="grid gap-3 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center" data-pool-provider-row={provider.id}>
      <div className="flex min-w-0 items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-muted/25 text-primary"><Boxes aria-hidden="true" className="h-4 w-4" /></span>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2"><h3 className="font-mono text-sm font-semibold">{provider.name}</h3><StatusBadge label={provider.status.health.state} tone={healthTone(provider.status.health.state)} /></div>
          <p className="mt-1 text-xs text-muted-foreground">{provider.status.health.message}</p>
        </div>
      </div>
      <Link className={cn(buttonVariants({ size: "sm", variant: "outline" }), "gap-2")} to={poolProviderPath(provider.id)}>
        <Settings2 aria-hidden="true" className="h-3.5 w-3.5" />{actionLabel}
      </Link>
    </div>
  );
}

function ProviderDetails({
  provider,
  canAdmin,
  detail,
  onRefresh,
}: {
  provider: PoolProviderView;
  canAdmin: boolean;
  detail: PluginDetail | null;
  onRefresh: () => Promise<void>;
}) {
  const pools = poolCapabilityView({ id: "storage.pooling", surface: "pools", providers: [{ ...provider, renderer: { id: provider.rendererId, mode: provider.rendererMode } }] }).pools;
  const configurePath = provider.source === "legacy" ? APP_PATHS.plugins : extensionDetailsPath(provider.id);
  const tailoredMergerfs = provider.id === "mergerfs" && detail !== null;
  return (
    <div className="space-y-5" data-pool-provider-details={provider.id}>
      <Link className={cn(buttonVariants({ size: "sm", variant: "ghost" }), "gap-2 px-0 hover:bg-transparent")} to={APP_PATHS.pools}><ArrowLeft aria-hidden="true" className="h-4 w-4" />Back to pools</Link>
      <PageHeader
        actions={canAdmin && !tailoredMergerfs ? <Link className={cn(buttonVariants({ variant: "secondary" }), "gap-2")} to={configurePath}><Settings2 aria-hidden="true" className="h-4 w-4" />Configure provider</Link> : undefined}
        description={detail?.description || "Storage pooling provider"}
        status={<StatusBadge label={provider.status.health.state} tone={healthTone(provider.status.health.state)} />}
        title={provider.name}
      />
      {tailoredMergerfs ? (
        <MergerfsProviderRenderer
          canConfigure={canAdmin}
          detail={detail}
          onRefresh={onRefresh}
          pools={pools}
          status={provider.status}
        />
      ) : (
        <>
          <GenericCapabilityRenderer status={provider.status} />
          {pools.length ? <section aria-labelledby="provider-pools-title"><h2 className="mb-3 font-mono text-sm font-semibold" id="provider-pools-title">Configured pools</h2><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{pools.map((pool) => <PoolCapabilityCard key={pool.id} pool={pool} />)}</div></section> : null}
          {!provider.status.lifecycle.configured ? <div className="border-l-2 border-warning bg-warning/5 px-4 py-3 text-sm"><p className="font-medium text-warning">Provider setup is required</p><p className="mt-1 text-muted-foreground">Configure this provider before it can create operational pool cards.</p></div> : null}
        </>
      )}
    </div>
  );
}

export function PoolsPage() {
  const { providerId } = useParams<{ providerId?: string }>();
  const { permissions } = useAuth();
  const canAdmin = permissions.includes("extensions.admin");
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [capability, setCapability] = useState<CapabilityDescriptor>({ id: "storage.pooling", surface: "pools", providers: [] });
  const [pluginDetails, setPluginDetails] = useState<Record<string, PluginDetail | null>>({});
  const [error, setError] = useState("");
  const [registryWarning, setRegistryWarning] = useState("");
  const [lastUpdated, setLastUpdated] = useState("Never");

  const load = useCallback(async (silent = false) => {
    if (!silent) setPhase("loading");
    const [registryResult, pluginsResult] = await Promise.allSettled([
      fetchCapability("storage.pooling"),
      fetchPlugins(),
    ]);
    const plugins = pluginsResult.status === "fulfilled" ? pluginsResult.value : [];
    const detailEntries: Array<[string, PluginDetail | null]> = [];
    const mergerfs = plugins.find((plugin) => plugin.id === "mergerfs" && plugin.installed);
    if (mergerfs) {
      const detail = await fetchPluginDetail("mergerfs").catch(() => null);
      detailEntries.push(["mergerfs", detail]);
    }
    const observedAt = new Date().toISOString();
    const legacy = adaptLegacyPoolingProviders(plugins, Object.fromEntries(detailEntries), observedAt);

    if (registryResult.status === "rejected" && pluginsResult.status === "rejected") {
      if (silent) {
        setRegistryWarning("Refresh failed; showing the last successful provider state.");
        return;
      }
      setError(getErrorMessage(registryResult.reason));
      setPhase("error");
      return;
    }
    const next = registryResult.status === "fulfilled"
      ? enrichPoolingCapability(registryResult.value, legacy)
      : legacy;
    setCapability(next);
    setPluginDetails(Object.fromEntries(detailEntries));
    setRegistryWarning(
      registryResult.status === "rejected" && legacy.providers.length
        ? "Capability registry unavailable; showing compatibility data from the existing MergerFS provider."
        : "",
    );
    setError("");
    setLastUpdated(formatClockTime(new Date()));
    setPhase("ready");
  }, []);

  useEffect(() => { void load(false); }, [load]);

  const view = useMemo(() => poolCapabilityView(capability), [capability]);
  const selectedProvider = providerId
    ? [...view.enabledProviders, ...view.availableProviders].find((provider) => provider.id === providerId)
    : null;

  if (providerId && phase === "ready" && selectedProvider) {
    return (
      <ProviderDetails
        canAdmin={canAdmin}
        detail={pluginDetails[selectedProvider.id] ?? null}
        onRefresh={() => load(true)}
        provider={selectedProvider}
      />
    );
  }

  if (providerId && phase === "ready" && !selectedProvider) {
    return <section className="space-y-5"><Link className={cn(buttonVariants({ size: "sm", variant: "ghost" }), "gap-2 px-0")} to={APP_PATHS.pools}><ArrowLeft aria-hidden="true" className="h-4 w-4" />Back to pools</Link><div className="flex min-h-64 flex-col items-center justify-center rounded-md border border-dashed border-border px-5 text-center"><CircleAlert aria-hidden="true" className="h-7 w-7 text-warning" /><h1 className="mt-3 font-mono text-base font-semibold">Pooling provider not found</h1><p className="mt-1 text-sm text-muted-foreground">The provider may be disabled, removed, or incompatible.</p></div></section>;
  }

  return (
    <section className="space-y-5 sm:space-y-6">
      <PageHeader
        actions={<>{canAdmin ? <Link className={cn(buttonVariants({ variant: "secondary" }), "gap-2")} to={APP_PATHS.extensions}><Plus aria-hidden="true" className="h-4 w-4" />Add provider</Link> : null}<Button className="gap-2" disabled={phase === "loading"} onClick={() => void load(false)} variant="secondary"><RefreshCw aria-hidden="true" className={cn("h-4 w-4", phase === "loading" && "animate-spin")} />refresh</Button></>}
        description={`${view.summary.totalPools} pools · synced ${lastUpdated}`}
        status={phase === "ready" ? <StatusBadge label={view.summary.warnings ? `${view.summary.warnings} warning${view.summary.warnings === 1 ? "" : "s"}` : "pooling ready"} tone={view.summary.warnings ? "warning" : "success"} /> : undefined}
        title="storage_pools"
      />

      {phase === "loading" ? <div aria-live="polite" className="flex min-h-56 items-center justify-center gap-2 rounded-md border border-border text-sm text-muted-foreground" role="status"><RefreshCw aria-hidden="true" className="h-4 w-4 animate-spin text-primary" />Loading pooling providers...</div> : null}
      {phase === "error" ? <div aria-live="assertive" className="border-l-2 border-danger bg-danger/5 px-4 py-4 text-sm text-danger" role="alert"><div className="flex items-center gap-2 font-medium"><TriangleAlert aria-hidden="true" className="h-4 w-4" />Pools are unavailable</div><p className="mt-1 text-muted-foreground">{error}</p><Button className="mt-3" onClick={() => void load(false)} size="sm" variant="outline">Retry</Button></div> : null}

      {phase === "ready" ? <PoolSummary view={view} /> : null}
      {registryWarning ? <div className="border-l-2 border-warning bg-warning/5 px-4 py-3 text-sm text-muted-foreground" data-pool-compatibility-warning>{registryWarning}</div> : null}

      {phase === "ready" && !view.enabledProviders.length ? (
        <div className="flex min-h-56 flex-col items-center justify-center rounded-md border border-dashed border-border px-5 text-center" data-pools-empty>
          <Database aria-hidden="true" className="h-7 w-7 text-dim" />
          <h2 className="mt-3 font-mono text-sm font-semibold">No pooling provider is enabled</h2>
          <p className="mt-1 max-w-lg text-sm text-muted-foreground">Enable a storage pooling provider to combine mounted disks into managed pools.</p>
          {canAdmin ? <Link className={cn(buttonVariants({ size: "sm" }), "mt-4 gap-2")} to={APP_PATHS.extensions}><Plus aria-hidden="true" className="h-4 w-4" />Add provider</Link> : null}
        </div>
      ) : null}

      {phase === "ready" && view.pools.length ? <section aria-labelledby="configured-pools-title"><div className="mb-3 flex items-center justify-between"><h2 className="font-mono text-sm font-semibold" id="configured-pools-title">Configured pools</h2><span className="text-xs text-dim">{view.summary.mountedPools}/{view.summary.totalPools} mounted</span></div><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{view.pools.map((pool) => <PoolCapabilityCard key={pool.id} pool={pool} />)}</div></section> : null}

      {phase === "ready" && view.setupProviders.length ? <section aria-labelledby="pool-setup-title" className="overflow-hidden rounded-md border border-border bg-card"><div className="border-b border-border px-4 py-3"><h2 className="font-mono text-sm font-semibold" id="pool-setup-title">Setup required</h2><p className="mt-1 text-xs text-muted-foreground">Enabled providers appear here until their first pool is configured.</p></div><div className="divide-y divide-border">{view.setupProviders.map((provider) => <ProviderRow key={provider.id} provider={provider} />)}</div></section> : null}

      {phase === "ready" && view.configuredProviders.filter((provider) => !view.pools.some((pool) => pool.providerId === provider.id)).length ? <section aria-labelledby="pool-provider-status-title" className="overflow-hidden rounded-md border border-border bg-card"><div className="border-b border-border px-4 py-3"><h2 className="font-mono text-sm font-semibold" id="pool-provider-status-title">Provider status</h2><p className="mt-1 text-xs text-muted-foreground">Configured providers that do not currently report individual pools.</p></div><div className="divide-y divide-border">{view.configuredProviders.filter((provider) => !view.pools.some((pool) => pool.providerId === provider.id)).map((provider) => <ProviderRow actionLabel="View" key={provider.id} provider={provider} />)}</div></section> : null}

      {phase === "ready" && view.availableProviders.length ? <section aria-labelledby="available-pool-providers-title" className="overflow-hidden rounded-md border border-border bg-card"><div className="border-b border-border px-4 py-3"><h2 className="font-mono text-sm font-semibold" id="available-pool-providers-title">Available providers</h2><p className="mt-1 text-xs text-muted-foreground">Installed pooling providers that are currently disabled.</p></div><div className="divide-y divide-border">{view.availableProviders.map((provider) => <ProviderRow actionLabel="Review" key={provider.id} provider={provider} />)}</div></section> : null}
    </section>
  );
}
