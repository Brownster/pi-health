import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  CircleAlert,
  Plus,
  RefreshCw,
  Settings2,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { Link, useParams } from "react-router-dom";

import {
  APP_PATHS,
  extensionDetailsPath,
  protectionProviderPath,
} from "@/app/route-contract";
import { useAuth } from "@/components/auth/auth-provider";
import { GenericCapabilityRenderer } from "@/components/capabilities/generic-capability-renderer";
import { ProtectionSetCard } from "@/components/storage/protection-set-card";
import { StatusBadge, type BadgeProps } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { fetchCapability, type CapabilityDescriptor, type CapabilityHealthState } from "@/lib/capabilities";
import { formatClockTime } from "@/lib/format";
import {
  adaptLegacyProtectionProviders,
  enrichProtectionCapability,
  protectionCapabilityView,
  type ProtectionProviderView,
} from "@/lib/protection-capabilities";
import { fetchPluginDetail, fetchPlugins, type PluginDetail } from "@/lib/storage-plugins";
import { cn } from "@/lib/utils";

type LoadPhase = "loading" | "ready" | "error";

function getErrorMessage(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : "Unable to load protection providers";
}

function healthTone(state: CapabilityHealthState): BadgeProps["tone"] {
  if (state === "healthy") return "success";
  if (state === "warning" || state === "unconfigured") return "warning";
  if (["error", "unavailable", "incompatible"].includes(state)) return "danger";
  return "neutral";
}

function formatMoment(value: string | null): string {
  if (!value) return "Not reported";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function ProtectionSummary({ view }: { view: ReturnType<typeof protectionCapabilityView> }) {
  const { summary } = view;
  const cells = [
    { label: "Protection sets", value: String(summary.totalSets), detail: `${view.enabledProviders.length} enabled provider${view.enabledProviders.length === 1 ? "" : "s"}` },
    { label: "Protected", value: summary.protectedTargets === null ? "Not reported" : String(summary.protectedTargets), detail: "Provider-reported targets" },
    { label: "Unprotected", value: summary.unprotectedTargets === null ? "Not reported" : String(summary.unprotectedTargets), detail: "Provider-reported targets" },
    { label: "Last run", value: formatMoment(summary.latestRunAt), detail: "Latest provider activity" },
    { label: "Next run", value: formatMoment(summary.nextRunAt), detail: summary.nextRunAt ? "Next scheduled activity" : "No next run reported" },
  ];
  return (
    <dl aria-label="Protection summary" className="grid grid-cols-2 overflow-hidden rounded-md border border-border bg-card lg:grid-cols-5" data-protection-summary>
      {cells.map((cell) => (
        <div className="min-w-0 border-b border-r border-border p-3 last:col-span-2 last:border-r-0 lg:border-b-0 lg:last:col-span-1" key={cell.label}>
          <dt className="font-mono text-[10px] uppercase text-dim">{cell.label}</dt>
          <dd className="mt-1 break-words text-sm font-semibold tabular-nums text-foreground">{cell.value}</dd>
          <p className="mt-1 truncate text-[11px] text-muted-foreground" title={cell.detail}>{cell.detail}</p>
        </div>
      ))}
    </dl>
  );
}

function ProviderRow({ provider, actionLabel = "Set up" }: { provider: ProtectionProviderView; actionLabel?: string }) {
  return (
    <div className="grid gap-3 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center" data-protection-provider-row={provider.id}>
      <div className="flex min-w-0 items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-muted/25 text-primary"><ShieldCheck aria-hidden="true" className="h-4 w-4" /></span>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2"><h3 className="font-mono text-sm font-semibold">{provider.name}</h3><StatusBadge label={provider.status.health.state} tone={healthTone(provider.status.health.state)} /></div>
          <p className="mt-1 text-xs text-muted-foreground">{provider.status.health.message}</p>
        </div>
      </div>
      <Link className={cn(buttonVariants({ size: "sm", variant: "outline" }), "gap-2")} to={protectionProviderPath(provider.id)}><Settings2 aria-hidden="true" className="h-3.5 w-3.5" />{actionLabel}</Link>
    </div>
  );
}

function ProviderDetails({ provider, canAdmin, detail }: { provider: ProtectionProviderView; canAdmin: boolean; detail: PluginDetail | null }) {
  const protectionSets = protectionCapabilityView({ id: "storage.protection", surface: "protection", providers: [{ ...provider, renderer: { id: provider.rendererId, mode: provider.rendererMode } }] }).protectionSets;
  const configurePath = provider.source === "legacy" ? APP_PATHS.plugins : extensionDetailsPath(provider.id);
  return (
    <div className="space-y-5" data-protection-provider-details={provider.id}>
      <Link className={cn(buttonVariants({ size: "sm", variant: "ghost" }), "gap-2 px-0 hover:bg-transparent")} to={APP_PATHS.protection}><ArrowLeft aria-hidden="true" className="h-4 w-4" />Back to protection</Link>
      <PageHeader
        actions={canAdmin ? <Link className={cn(buttonVariants({ variant: "secondary" }), "gap-2")} to={configurePath}><Settings2 aria-hidden="true" className="h-4 w-4" />Configure provider</Link> : undefined}
        description={detail?.description || "Storage protection provider"}
        status={<StatusBadge label={provider.status.health.state} tone={healthTone(provider.status.health.state)} />}
        title={provider.name}
      />
      <GenericCapabilityRenderer status={provider.status} />
      {protectionSets.length ? <section aria-labelledby="provider-protection-title"><h2 className="mb-3 font-mono text-sm font-semibold" id="provider-protection-title">Protection sets</h2><div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{protectionSets.map((item) => <ProtectionSetCard key={item.id} protectionSet={item} />)}</div></section> : null}
      {!provider.status.lifecycle.configured ? <div className="border-l-2 border-warning bg-warning/5 px-4 py-3 text-sm"><p className="font-medium text-warning">Provider setup is required</p><p className="mt-1 text-muted-foreground">Configure this provider before it can report protected targets.</p></div> : null}
    </div>
  );
}

export function ProtectionPage() {
  const { providerId } = useParams<{ providerId?: string }>();
  const { permissions } = useAuth();
  const canAdmin = permissions.includes("extensions.admin");
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [capability, setCapability] = useState<CapabilityDescriptor>({ id: "storage.protection", surface: "protection", providers: [] });
  const [pluginDetails, setPluginDetails] = useState<Record<string, PluginDetail | null>>({});
  const [error, setError] = useState("");
  const [registryWarning, setRegistryWarning] = useState("");
  const [lastUpdated, setLastUpdated] = useState("Never");

  const load = useCallback(async () => {
    setPhase("loading");
    const [registryResult, pluginsResult] = await Promise.allSettled([
      fetchCapability("storage.protection"),
      fetchPlugins(),
    ]);
    const plugins = pluginsResult.status === "fulfilled" ? pluginsResult.value : [];
    const detailEntries: Array<[string, PluginDetail | null]> = [];
    const snapraid = plugins.find((plugin) => plugin.id === "snapraid" && plugin.installed);
    if (snapraid) detailEntries.push(["snapraid", await fetchPluginDetail("snapraid").catch(() => null)]);
    const legacy = adaptLegacyProtectionProviders(plugins, Object.fromEntries(detailEntries), new Date().toISOString());

    if (registryResult.status === "rejected" && pluginsResult.status === "rejected") {
      setError(getErrorMessage(registryResult.reason));
      setPhase("error");
      return;
    }
    const next = registryResult.status === "fulfilled"
      ? enrichProtectionCapability(registryResult.value, legacy)
      : legacy;
    setCapability(next);
    setPluginDetails(Object.fromEntries(detailEntries));
    setRegistryWarning(
      registryResult.status === "rejected" && legacy.providers.length
        ? "Capability registry unavailable; showing compatibility data from the existing SnapRAID provider."
        : "",
    );
    setError("");
    setLastUpdated(formatClockTime(new Date()));
    setPhase("ready");
  }, []);

  useEffect(() => { void load(); }, [load]);

  const view = useMemo(() => protectionCapabilityView(capability), [capability]);
  const selectedProvider = providerId
    ? [...view.enabledProviders, ...view.availableProviders].find((provider) => provider.id === providerId)
    : null;

  if (providerId && phase === "ready" && selectedProvider) {
    return <ProviderDetails canAdmin={canAdmin} detail={pluginDetails[selectedProvider.id] ?? null} provider={selectedProvider} />;
  }

  if (providerId && phase === "ready" && !selectedProvider) {
    return <section className="space-y-5"><Link className={cn(buttonVariants({ size: "sm", variant: "ghost" }), "gap-2 px-0")} to={APP_PATHS.protection}><ArrowLeft aria-hidden="true" className="h-4 w-4" />Back to protection</Link><div className="flex min-h-64 flex-col items-center justify-center rounded-md border border-dashed border-border px-5 text-center"><CircleAlert aria-hidden="true" className="h-7 w-7 text-warning" /><h1 className="mt-3 font-mono text-base font-semibold">Protection provider not found</h1><p className="mt-1 text-sm text-muted-foreground">The provider may be disabled, removed, or incompatible.</p></div></section>;
  }

  const providerStatusRows = view.configuredProviders.filter((provider) =>
    !view.protectionSets.some((item) => item.providerId === provider.id),
  );
  return (
    <section className="space-y-5 sm:space-y-6">
      <PageHeader
        actions={<>{canAdmin ? <Link className={cn(buttonVariants({ variant: "secondary" }), "gap-2")} to={APP_PATHS.extensions}><Plus aria-hidden="true" className="h-4 w-4" />Add provider</Link> : null}<Button className="gap-2" disabled={phase === "loading"} onClick={() => void load()} variant="secondary"><RefreshCw aria-hidden="true" className={cn("h-4 w-4", phase === "loading" && "animate-spin")} />refresh</Button></>}
        description={`${view.summary.totalSets} protection sets · synced ${lastUpdated}`}
        status={phase === "ready" ? <StatusBadge label={view.summary.warnings ? `${view.summary.warnings} warning${view.summary.warnings === 1 ? "" : "s"}` : "protection ready"} tone={view.summary.warnings ? "warning" : "success"} /> : undefined}
        title="storage_protection"
      />

      {phase === "loading" ? <div aria-live="polite" className="flex min-h-56 items-center justify-center gap-2 rounded-md border border-border text-sm text-muted-foreground" role="status"><RefreshCw aria-hidden="true" className="h-4 w-4 animate-spin text-primary" />Loading protection providers...</div> : null}
      {phase === "error" ? <div aria-live="assertive" className="border-l-2 border-danger bg-danger/5 px-4 py-4 text-sm text-danger" role="alert"><div className="flex items-center gap-2 font-medium"><TriangleAlert aria-hidden="true" className="h-4 w-4" />Protection is unavailable</div><p className="mt-1 text-muted-foreground">{error}</p><Button className="mt-3" onClick={() => void load()} size="sm" variant="outline">Retry</Button></div> : null}
      {phase === "ready" ? <ProtectionSummary view={view} /> : null}
      {registryWarning ? <div className="border-l-2 border-warning bg-warning/5 px-4 py-3 text-sm text-muted-foreground" data-protection-compatibility-warning>{registryWarning}</div> : null}

      {phase === "ready" && !view.enabledProviders.length ? <div className="flex min-h-56 flex-col items-center justify-center rounded-md border border-dashed border-border px-5 text-center" data-protection-empty><ShieldCheck aria-hidden="true" className="h-7 w-7 text-dim" /><h2 className="mt-3 font-mono text-sm font-semibold">No protection provider is enabled</h2><p className="mt-1 max-w-lg text-sm text-muted-foreground">Enable a protection provider to manage parity, replication, snapshots, or backups.</p>{canAdmin ? <Link className={cn(buttonVariants({ size: "sm" }), "mt-4 gap-2")} to={APP_PATHS.extensions}><Plus aria-hidden="true" className="h-4 w-4" />Add provider</Link> : null}</div> : null}
      {phase === "ready" && view.protectionSets.length ? <section aria-labelledby="protection-sets-title"><div className="mb-3 flex items-center justify-between gap-3"><h2 className="font-mono text-sm font-semibold" id="protection-sets-title">Protection sets</h2><span className="text-xs text-dim">{view.summary.protectedTargets ?? "—"} protected</span></div><div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{view.protectionSets.map((item) => <ProtectionSetCard key={item.id} protectionSet={item} />)}</div></section> : null}
      {phase === "ready" && view.setupProviders.length ? <section aria-labelledby="protection-setup-title" className="overflow-hidden rounded-md border border-border bg-card"><div className="border-b border-border px-4 py-3"><h2 className="font-mono text-sm font-semibold" id="protection-setup-title">Setup required</h2><p className="mt-1 text-xs text-muted-foreground">Enabled providers appear here until their first protection set is configured.</p></div><div className="divide-y divide-border">{view.setupProviders.map((provider) => <ProviderRow key={provider.id} provider={provider} />)}</div></section> : null}
      {phase === "ready" && providerStatusRows.length ? <section aria-labelledby="protection-provider-status-title" className="overflow-hidden rounded-md border border-border bg-card"><div className="border-b border-border px-4 py-3"><h2 className="font-mono text-sm font-semibold" id="protection-provider-status-title">Provider status</h2><p className="mt-1 text-xs text-muted-foreground">Configured providers that do not currently report protection sets.</p></div><div className="divide-y divide-border">{providerStatusRows.map((provider) => <ProviderRow actionLabel="View" key={provider.id} provider={provider} />)}</div></section> : null}
      {phase === "ready" && view.availableProviders.length ? <section aria-labelledby="available-protection-providers-title" className="overflow-hidden rounded-md border border-border bg-card"><div className="border-b border-border px-4 py-3"><h2 className="font-mono text-sm font-semibold" id="available-protection-providers-title">Available providers</h2><p className="mt-1 text-xs text-muted-foreground">Installed protection providers that are currently disabled.</p></div><div className="divide-y divide-border">{view.availableProviders.map((provider) => <ProviderRow actionLabel="Review" key={provider.id} provider={provider} />)}</div></section> : null}
    </section>
  );
}
