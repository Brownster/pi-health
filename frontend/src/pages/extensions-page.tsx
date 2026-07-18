import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  Box,
  ChevronRight,
  CircleAlert,
  Download,
  Loader2,
  PackageOpen,
  Plus,
  Power,
  RefreshCw,
  Trash2,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { APP_PATHS, extensionDetailsPath } from "@/app/route-contract";
import {
  ExtensionInstallDialog,
  ExtensionLifecycleDialog,
  type ExtensionDialogAction,
} from "@/components/extensions/extension-lifecycle-dialogs";
import { useAuth } from "@/components/auth/auth-provider";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { SettingsNavigation } from "@/components/settings/settings-navigation";
import {
  type CapabilityRegistryDiagnostic,
  type ExtensionDescriptor,
  fetchExtensionDetails,
  fetchExtensionIndex,
  installExtension,
  removeExtension,
  transitionExtension,
} from "@/lib/capabilities";
import {
  capabilitySurfaceLink,
  extensionLifecycleActions,
  extensionUpdateLabel,
  groupExtensions,
  healthTone,
  humanizeCapabilityId,
} from "@/lib/extensions";
import { cn } from "@/lib/utils";

function getErrorMessage(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : "Unable to load extensions";
}

function stateLabel(value: string): string {
  return value.replace(/[_-]+/g, " ");
}

function Diagnostics({ errors }: { errors: CapabilityRegistryDiagnostic[] }) {
  if (!errors.length) return null;
  return (
    <section aria-labelledby="extension-diagnostics-title" className="border-l-2 border-warning bg-warning/5 px-4 py-3">
      <div className="flex items-center gap-2 text-warning">
        <TriangleAlert aria-hidden="true" className="h-4 w-4 shrink-0" />
        <h2 className="font-mono text-sm font-semibold" id="extension-diagnostics-title">
          Extension diagnostics
        </h2>
      </div>
      <div className="mt-2 divide-y divide-warning/15">
        {errors.map((error, index) => (
          <div className="grid gap-1 py-2 text-xs sm:grid-cols-[minmax(10rem,0.35fr)_1fr]" key={`${error.provider_id ?? "registry"}-${error.code}-${index}`}>
            <code className="break-all text-warning">{error.code}</code>
            <p className="text-muted-foreground">{error.message}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function ExtensionRow({ extension }: { extension: ExtensionDescriptor }) {
  const operational = extension.capabilities.filter((capability) => capability.operational).length;
  return (
    <Link
      className="group grid min-h-20 cursor-pointer gap-3 px-4 py-3 transition-colors duration-200 hover:bg-muted/35 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:grid-cols-[minmax(12rem,1.15fr)_minmax(9rem,0.65fr)_minmax(9rem,0.65fr)_auto] sm:items-center"
      data-extension-id={extension.id}
      to={extensionDetailsPath(extension.id)}
    >
      <div className="flex min-w-0 items-start gap-3">
        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-muted/30 text-muted-foreground">
          <PackageOpen aria-hidden="true" className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="truncate font-mono text-sm font-semibold text-foreground">{extension.name}</p>
          <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{extension.description || extension.id}</p>
          <div className="mt-2 flex flex-wrap gap-1.5 sm:hidden">
            <StatusBadge label={stateLabel(extension.health.state)} tone={healthTone(extension.health.state)} />
            <Badge>{extension.version || "version unknown"}</Badge>
          </div>
        </div>
      </div>
      <div className="hidden min-w-0 sm:block">
        <p className="font-mono text-xs text-foreground">{extension.version || "unknown"}</p>
        <p className="mt-1 truncate text-xs text-dim">{extension.source}</p>
      </div>
      <div className="hidden sm:block">
        <StatusBadge label={stateLabel(extension.health.state)} tone={healthTone(extension.health.state)} />
        <p className="mt-1 text-xs text-dim">{operational}/{extension.capabilities.length} providers ready</p>
      </div>
      <div className="flex items-center justify-between gap-3 sm:justify-end">
        <Badge tone={extension.compatibility === "compatible" ? "success" : extension.compatibility === "incompatible" ? "danger" : "neutral"}>
          {extension.compatibility}
        </Badge>
        <ChevronRight aria-hidden="true" className="h-4 w-4 text-dim transition-colors group-hover:text-foreground" />
      </div>
    </Link>
  );
}

function ExtensionListPage() {
  const { permissions } = useAuth();
  const [extensions, setExtensions] = useState<ExtensionDescriptor[]>([]);
  const [diagnostics, setDiagnostics] = useState<CapabilityRegistryDiagnostic[]>([]);
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [installOpen, setInstallOpen] = useState(false);
  const [installPending, setInstallPending] = useState(false);
  const [operationNotice, setOperationNotice] = useState<{ tone: "success" | "danger"; message: string } | null>(null);
  const canAdmin = permissions.includes("extensions.admin");

  const load = useCallback(async () => {
    setPhase("loading");
    try {
      const result = await fetchExtensionIndex();
      setExtensions(result.extensions);
      setDiagnostics(result.errors);
      setError("");
      setPhase("ready");
    } catch (caughtError) {
      setError(getErrorMessage(caughtError));
      setPhase("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const groups = groupExtensions(extensions);
  const attentionCount = extensions.filter((extension) => !["healthy", "disabled"].includes(extension.health.state)).length;

  const runInstall = async (values: { type: "github"; source: string; id?: string }) => {
    setInstallPending(true);
    setOperationNotice(null);
    try {
      const result = await installExtension(values);
      setInstallOpen(false);
      setOperationNotice({
        tone: "success",
        message: `Extension ${result.id || "package"} installed. Restart LimeOS to load the provider.`,
      });
      await load();
    } catch (caughtError) {
      setInstallOpen(false);
      setOperationNotice({ tone: "danger", message: getErrorMessage(caughtError) });
    } finally {
      setInstallPending(false);
    }
  };

  return (
    <section className="space-y-5 sm:space-y-6">
      <PageHeader
        actions={
          <div className="flex flex-wrap gap-2">
            {canAdmin ? <Button className="gap-2" data-extension-install-open onClick={() => setInstallOpen(true)}><Plus aria-hidden="true" className="h-4 w-4" />Install</Button> : null}
            <Button className="gap-2" disabled={phase === "loading"} onClick={() => void load()} variant="secondary">
              <RefreshCw aria-hidden="true" className={cn("h-4 w-4", phase === "loading" ? "animate-spin" : "")} />
              refresh
            </Button>
          </div>
        }
        description="Settings / Advanced · installed capability providers"
        status={phase === "ready" ? <StatusBadge label={`${extensions.length} installed`} tone={attentionCount ? "warning" : "success"} /> : undefined}
        title="extensions"
      />

      <Diagnostics errors={diagnostics} />

      {operationNotice ? (
        <div aria-live={operationNotice.tone === "danger" ? "assertive" : "polite"} className={cn("border-l-2 px-4 py-3 text-sm", operationNotice.tone === "danger" ? "border-danger bg-danger/5 text-danger" : "border-success bg-success/5 text-success")} data-extension-operation-notice role={operationNotice.tone === "danger" ? "alert" : "status"}>
          {operationNotice.message}
        </div>
      ) : null}

      {phase === "loading" ? (
        <div aria-live="polite" className="flex min-h-56 items-center justify-center gap-2 rounded-md border border-border text-sm text-muted-foreground" role="status">
          <RefreshCw aria-hidden="true" className="h-4 w-4 animate-spin text-primary" />
          Loading extensions...
        </div>
      ) : null}

      {phase === "error" ? (
        <div aria-live="assertive" className="border-l-2 border-danger bg-danger/5 px-4 py-4 text-sm text-danger" role="alert">
          <div className="flex items-center gap-2 font-medium">
            <CircleAlert aria-hidden="true" className="h-4 w-4" />
            Extension registry is unavailable
          </div>
          <p className="mt-1 text-muted-foreground">{error}</p>
        </div>
      ) : null}

      {phase === "ready" && !groups.length ? (
        <div className="flex min-h-56 flex-col items-center justify-center rounded-md border border-dashed border-border px-5 text-center">
          <PackageOpen aria-hidden="true" className="h-7 w-7 text-dim" />
          <h2 className="mt-3 font-mono text-sm font-semibold">No extensions discovered</h2>
          <p className="mt-1 max-w-lg text-sm text-muted-foreground">Installed providers will appear here when their capability adapters are available.</p>
        </div>
      ) : null}

      {phase === "ready" && groups.length ? (
        <div className="space-y-5">
          {groups.map((group) => (
            <section aria-labelledby={`extension-group-${group.id}`} key={group.id}>
              <div className="mb-2 flex items-center justify-between gap-3">
                <h2 className="font-mono text-xs font-semibold uppercase text-muted-foreground" id={`extension-group-${group.id}`}>
                  {group.label}
                </h2>
                <span className="font-mono text-[11px] text-dim">{group.extensions.length}</span>
              </div>
              <div className="overflow-hidden rounded-md border border-border bg-card divide-y divide-border">
                {group.extensions.map((extension) => <ExtensionRow extension={extension} key={extension.id} />)}
              </div>
            </section>
          ))}
        </div>
      ) : null}

      {installOpen ? <ExtensionInstallDialog onClose={() => setInstallOpen(false)} onConfirm={(values) => void runInstall(values)} pending={installPending} /> : null}
    </section>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0 bg-card px-4 py-3">
      <dt className="font-mono text-[10px] uppercase text-dim">{label}</dt>
      <dd className="mt-1 break-words text-sm text-foreground">{children}</dd>
    </div>
  );
}

function ExtensionDetailPage({ extensionId }: { extensionId: string }) {
  const navigate = useNavigate();
  const { permissions } = useAuth();
  const [extension, setExtension] = useState<ExtensionDescriptor | null>(null);
  const [diagnostics, setDiagnostics] = useState<CapabilityRegistryDiagnostic[]>([]);
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [dialogAction, setDialogAction] = useState<ExtensionDialogAction | null>(null);
  const [operationPending, setOperationPending] = useState(false);
  const [operationNotice, setOperationNotice] = useState<{ tone: "success" | "danger"; message: string } | null>(null);
  const canAdmin = permissions.includes("extensions.admin");

  const load = useCallback(async () => {
    setPhase("loading");
    try {
      const result = await fetchExtensionDetails(extensionId);
      setExtension(result.extension);
      setDiagnostics(result.errors);
      setError("");
      setPhase("ready");
    } catch (caughtError) {
      setExtension(null);
      setError(getErrorMessage(caughtError));
      setPhase("error");
    }
  }, [extensionId]);

  useEffect(() => {
    void load();
  }, [load]);

  const runLifecycle = async (action: ExtensionDialogAction) => {
    if (!extension) return;
    setOperationPending(true);
    setOperationNotice(null);
    try {
      if (action === "remove") {
        await removeExtension(extension.id);
        setDialogAction(null);
        navigate(APP_PATHS.extensions, { replace: true });
        return;
      }
      const result = await transitionExtension(extension.id, action);
      setDialogAction(null);
      setOperationNotice({
        tone: "success",
        message: `${extension.name} ${action} completed.${result.restart_required ? " Restart LimeOS to apply the change." : ""}`,
      });
      await load();
    } catch (caughtError) {
      setDialogAction(null);
      setOperationNotice({ tone: "danger", message: getErrorMessage(caughtError) });
    } finally {
      setOperationPending(false);
    }
  };

  if (phase === "loading") {
    return <div aria-live="polite" className="flex min-h-56 items-center justify-center gap-2 text-sm text-muted-foreground" role="status"><RefreshCw aria-hidden="true" className="h-4 w-4 animate-spin text-primary" />Loading extension...</div>;
  }

  if (phase === "error" || !extension) {
    return (
      <section className="space-y-5">
        <Link className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "gap-2")} to={APP_PATHS.extensions}><ArrowLeft aria-hidden="true" className="h-4 w-4" />Extensions</Link>
        <div className="border-l-2 border-danger bg-danger/5 px-4 py-4 text-sm text-danger" role="alert"><p className="font-medium">Unable to load extension</p><p className="mt-1 text-muted-foreground">{error}</p></div>
      </section>
    );
  }

  return (
    <section className="space-y-5 sm:space-y-6">
      <Link className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "gap-2 px-2")} to={APP_PATHS.extensions}><ArrowLeft aria-hidden="true" className="h-4 w-4" />Extensions</Link>
      <PageHeader
        actions={<Button className="gap-2" onClick={() => void load()} variant="secondary"><RefreshCw aria-hidden="true" className="h-4 w-4" />refresh</Button>}
        description={extension.description || "Capability provider extension"}
        status={<StatusBadge label={stateLabel(extension.health.state)} tone={healthTone(extension.health.state)} />}
        title={extension.name}
      />

      <Diagnostics errors={diagnostics} />

      {operationNotice ? (
        <div aria-live={operationNotice.tone === "danger" ? "assertive" : "polite"} className={cn("border-l-2 px-4 py-3 text-sm", operationNotice.tone === "danger" ? "border-danger bg-danger/5 text-danger" : "border-success bg-success/5 text-success")} data-extension-operation-notice role={operationNotice.tone === "danger" ? "alert" : "status"}>
          {operationNotice.message}
        </div>
      ) : null}

      <section aria-labelledby="extension-package-title">
        <h2 className="mb-2 font-mono text-xs font-semibold uppercase text-muted-foreground" id="extension-package-title">Package</h2>
        <dl className="grid gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
          <Fact label="Version"><span className="font-mono">{extension.version || "unknown"}</span></Fact>
          <Fact label="Source"><span className="font-mono text-xs">{extension.source}</span></Fact>
          <Fact label="Runtime"><span className="font-mono text-xs">{stateLabel(extension.runtime_kind)}</span></Fact>
          <Fact label="Update"><span className="font-mono text-xs">{extensionUpdateLabel(extension)}</span></Fact>
        </dl>
        <div className="mt-3 flex flex-wrap gap-2">
          <StatusBadge label={extension.installed ? "installed" : "not installed"} tone={extension.installed ? "success" : "neutral"} />
          <StatusBadge label={extension.enabled ? "enabled" : "disabled"} tone={extension.enabled ? "success" : "neutral"} />
          <StatusBadge label={extension.compatibility} tone={extension.compatibility === "compatible" ? "success" : extension.compatibility === "incompatible" ? "danger" : "neutral"} />
          <StatusBadge label={`contract ${extension.contract_state}`} tone={extension.contract_state === "valid" ? "success" : "danger"} />
        </div>
        <p className="mt-3 text-sm text-muted-foreground">{extension.health.message}</p>
      </section>

      <section aria-labelledby="extension-administration-title">
        <h2 className="mb-2 font-mono text-xs font-semibold uppercase text-muted-foreground" id="extension-administration-title">Administration</h2>
        <div className="rounded-md border border-border bg-card px-4 py-4">
          {extensionLifecycleActions(extension).length ? (
            canAdmin ? (
              <div className="flex flex-wrap gap-2">
                {extensionLifecycleActions(extension).map((action) => {
                  const Icon = action === "remove" ? Trash2 : action === "repair" ? Wrench : action === "update" ? Download : Power;
                  const removeBlocked = action === "remove" && extension.enabled;
                  return (
                    <Button
                      className={cn("gap-2", action === "remove" ? "border-danger/30 text-danger hover:bg-danger/10" : "")}
                      data-extension-action={action}
                      disabled={operationPending || removeBlocked}
                      key={action}
                      onClick={() => setDialogAction(action)}
                      title={removeBlocked ? "Disable this extension before removing it" : undefined}
                      variant="outline"
                    >
                      {operationPending ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : <Icon aria-hidden="true" className="h-4 w-4" />}
                      {action.charAt(0).toUpperCase() + action.slice(1)}
                    </Button>
                  );
                })}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Administrator access is required to change extension packages.</p>
            )
          ) : (
            <p className="text-sm text-muted-foreground">This provider is managed from its owning LimeOS page.</p>
          )}
        </div>
      </section>

      <section aria-labelledby="extension-capabilities-title">
        <div className="mb-2 flex items-center justify-between gap-3">
          <h2 className="font-mono text-xs font-semibold uppercase text-muted-foreground" id="extension-capabilities-title">Capabilities</h2>
          <span className="font-mono text-[11px] text-dim">{extension.capabilities.length}</span>
        </div>
        {extension.capabilities.length ? (
          <div className="overflow-hidden rounded-md border border-border bg-card divide-y divide-border">
            {extension.capabilities.map((capability) => {
              const link = capabilitySurfaceLink(capability.surface);
              return (
                <div className="grid gap-3 px-4 py-3 sm:grid-cols-[minmax(12rem,1fr)_auto] sm:items-center" data-capability-id={capability.id} key={capability.id}>
                  <div className="flex min-w-0 items-start gap-3">
                    <Box aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                    <div className="min-w-0">
                      <p className="font-mono text-sm font-semibold">{humanizeCapabilityId(capability.id)}</p>
                      <p className="mt-0.5 break-all font-mono text-xs text-dim">{capability.id}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{capability.status.health.message}</p>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                    <StatusBadge label={stateLabel(capability.status.health.state)} tone={healthTone(capability.status.health.state)} />
                    {link ? (
                      <Link className={cn(buttonVariants({ variant: "outline", size: "sm" }), "gap-2")} to={link}>Open <ArrowUpRight aria-hidden="true" className="h-3.5 w-3.5" /></Link>
                    ) : (
                      <Badge>page not available yet</Badge>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="rounded-md border border-dashed border-border px-4 py-6 text-sm text-muted-foreground">No usable capabilities were declared. Review the diagnostics above.</div>
        )}
      </section>

      {dialogAction ? <ExtensionLifecycleDialog action={dialogAction} extension={extension} onClose={() => setDialogAction(null)} onConfirm={() => void runLifecycle(dialogAction)} pending={operationPending} /> : null}
    </section>
  );
}

export function ExtensionsPage() {
  const { extensionId } = useParams<{ extensionId: string }>();
  return (
    <div className="space-y-5 sm:space-y-6">
      <SettingsNavigation />
      {extensionId ? <ExtensionDetailPage extensionId={extensionId} /> : <ExtensionListPage />}
    </div>
  );
}
