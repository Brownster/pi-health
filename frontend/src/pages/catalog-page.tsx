import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  CheckCircle2,
  FolderTree,
  Loader2,
  RefreshCw,
  Rocket,
  ShieldCheck,
  Trash2,
  TriangleAlert,
} from "lucide-react";

import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import { PageHeader } from "@/components/ui/page-header";
import {
  type CatalogField,
  type CatalogItem,
  fetchCatalog,
  fetchCatalogItemFields,
  installCatalogItem,
  removeCatalogItem,
} from "@/lib/catalog";
import { formatClockTime } from "@/lib/format";
import { runMediaQuickstart } from "@/lib/media-quickstart";
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 30_000;

interface ActionNotice {
  message: string;
  tone: "success" | "error";
}

type AsyncStatus = "idle" | "loading" | "ready" | "error";

interface InstallModalState {
  open: boolean;
  itemId: string;
  itemName: string;
  status: AsyncStatus;
  fields: CatalogField[];
  values: Record<string, string>;
  targetStack: string;
  newStackName: string;
  error: string | null;
  saving: boolean;
}

type QuickstartStatus = "idle" | "running" | "success" | "error";

interface QuickstartState {
  open: boolean;
  status: QuickstartStatus;
  stackName: string;
  lines: string[];
  error: string | null;
}

const EMPTY_INSTALL: InstallModalState = {
  open: false,
  itemId: "",
  itemName: "",
  status: "idle",
  fields: [],
  values: {},
  targetStack: "new",
  newStackName: "",
  error: null,
  saving: false,
};

const EMPTY_QUICKSTART: QuickstartState = {
  open: false,
  status: "idle",
  stackName: "media",
  lines: [],
  error: null,
};

function getErrorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : "Unable to complete the request";
}

function installationKey(itemId: string, stack: string): string {
  return `${itemId}:${stack}`;
}

function getDefaultTarget(item: CatalogItem, items: CatalogItem[], stacks: string[]): string {
  if (!item.requires.length) {
    return "new";
  }
  const dependencies = item.requires.map(
    (dependencyId) => items.find((candidate) => candidate.id === dependencyId)?.installedStacks ?? [],
  );
  return stacks.find((stack) => dependencies.every((installedStacks) => installedStacks.includes(stack))) ?? "new";
}

export function CatalogPage() {
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [availableStacks, setAvailableStacks] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState("Never");
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [pendingInstallation, setPendingInstallation] = useState<string | null>(null);
  const [confirmRemoveInstallation, setConfirmRemoveInstallation] = useState<string | null>(null);
  const [installModal, setInstallModal] = useState<InstallModalState>(EMPTY_INSTALL);
  const [quickstart, setQuickstart] = useState<QuickstartState>(EMPTY_QUICKSTART);
  const isMountedRef = useRef(true);

  const loadCatalog = useCallback(async (reason: "initial" | "manual" | "poll") => {
    if (reason === "initial") {
      setIsLoading(true);
    }
    if (reason === "manual") {
      setIsRefreshing(true);
    }
    try {
      const next = await fetchCatalog();
      if (!isMountedRef.current) {
        return;
      }
      setItems(next.items);
      setAvailableStacks(next.availableStacks);
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
        }
        if (reason === "manual") {
          setIsRefreshing(false);
        }
      }
    }
  }, []);

  const onRemove = useCallback(
    async (item: CatalogItem, stack: string) => {
      const key = installationKey(item.id, stack);
      setConfirmRemoveInstallation(null);
      setPendingInstallation(key);
      try {
        await removeCatalogItem(item.id, stack);
        if (isMountedRef.current) {
          setActionNotice({ tone: "success", message: `Removed ${item.name} from ${stack}` });
          await loadCatalog("manual");
        }
      } catch (caughtError) {
        if (isMountedRef.current) {
          setActionNotice({ tone: "error", message: getErrorMessage(caughtError) });
        }
      } finally {
        if (isMountedRef.current) {
          setPendingInstallation(null);
        }
      }
    },
    [loadCatalog],
  );

  const onOpenInstall = useCallback(
    async (item: CatalogItem) => {
      setInstallModal({
        ...EMPTY_INSTALL,
        open: true,
        itemId: item.id,
        itemName: item.name,
        status: "loading",
        targetStack: getDefaultTarget(item, items, availableStacks),
        newStackName: item.id,
      });
      try {
        const fields = await fetchCatalogItemFields(item.id);
        if (!isMountedRef.current) {
          return;
        }
        const values: Record<string, string> = {};
        for (const field of fields) {
          values[field.key] = field.default;
        }
        setInstallModal((current) =>
          current.itemId === item.id && current.open
            ? { ...current, status: "ready", fields, values }
            : current,
        );
      } catch (caughtError) {
        if (isMountedRef.current) {
          setInstallModal((current) =>
            current.itemId === item.id && current.open
              ? { ...current, status: "error", error: getErrorMessage(caughtError) }
              : current,
          );
        }
      }
    },
    [availableStacks, items],
  );

  const submitInstall = useCallback(async () => {
    const stackName = installModal.targetStack === "new" ? installModal.newStackName.trim() : "";
    if (installModal.targetStack === "new" && !stackName) {
      setInstallModal((current) => ({ ...current, error: "New stack name is required" }));
      return;
    }
    setInstallModal((current) => ({ ...current, saving: true, error: null }));
    try {
      await installCatalogItem(
        installModal.itemId,
        installModal.values,
        installModal.targetStack,
        stackName,
      );
      if (!isMountedRef.current) {
        return;
      }
      const name = installModal.itemName;
      setInstallModal(EMPTY_INSTALL);
      setActionNotice({ tone: "success", message: `Installed ${name}` });
      await loadCatalog("manual");
    } catch (caughtError) {
      if (isMountedRef.current) {
        setInstallModal((current) => ({ ...current, saving: false, error: getErrorMessage(caughtError) }));
      }
    }
  }, [installModal, loadCatalog]);

  const submitQuickstart = useCallback(async () => {
    const stackName = quickstart.stackName.trim();
    if (!stackName) {
      setQuickstart((current) => ({ ...current, error: "Stack name is required" }));
      return;
    }
    setQuickstart((current) => ({
      ...current,
      status: "running",
      stackName,
      lines: ["Preparing media quickstart..."],
      error: null,
    }));
    try {
      await runMediaQuickstart({
        stack: stackName,
        values: { USE_VPN: "true" },
        onEvent: (event) => {
          if (!isMountedRef.current) {
            return;
          }
          const line = event.error || event.line;
          if (line) {
            setQuickstart((current) => ({
              ...current,
              lines: [...current.lines, line],
              error: event.error ?? current.error,
            }));
          }
          if (event.error) {
            setQuickstart((current) => ({ ...current, status: "error", error: event.error ?? current.error }));
          } else if (event.done) {
            setQuickstart((current) => ({ ...current, status: "success" }));
          }
        },
      });
      if (!isMountedRef.current) {
        return;
      }
      setActionNotice({ tone: "success", message: `Media quickstart completed for ${stackName}` });
      await loadCatalog("manual");
    } catch (caughtError) {
      if (isMountedRef.current) {
        setQuickstart((current) => ({
          ...current,
          status: "error",
          error: getErrorMessage(caughtError),
          lines: [...current.lines, getErrorMessage(caughtError)],
        }));
      }
    }
  }, [loadCatalog, quickstart.stackName]);

  useEffect(() => {
    isMountedRef.current = true;
    void loadCatalog("initial");
    const intervalId = window.setInterval(() => void loadCatalog("poll"), POLL_INTERVAL_MS);
    return () => {
      isMountedRef.current = false;
      window.clearInterval(intervalId);
    };
  }, [loadCatalog]);

  const installedCount = items.reduce((count, item) => count + item.installedStacks.length, 0);
  const modalItem = items.find((item) => item.id === installModal.itemId);

  return (
    <section className="space-y-4 sm:space-y-6">
      <PageHeader
        actions={
          <Button
            className="gap-2"
            disabled={isRefreshing}
            onClick={() => void loadCatalog("manual")}
            variant="secondary"
          >
            <RefreshCw aria-hidden="true" className={cn("h-4 w-4", isRefreshing ? "animate-spin" : "")} />
            {isRefreshing ? "refreshing" : "refresh"}
          </Button>
        }
        description={`${installedCount} installations · ${items.length} catalog apps`}
        title="app_catalog"
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

      {error && !items.length ? (
        <Card className="border-danger/30">
          <CardContent className="flex flex-col items-start gap-3 p-4 sm:p-6">
            <p className="text-sm font-medium text-danger">Unable to load catalog</p>
            <p className="text-sm text-muted-foreground">{error}</p>
            <Button onClick={() => void loadCatalog("manual")} variant="outline">
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : null}

      <Card className="overflow-hidden border-info/30 bg-gradient-to-br from-info/10 via-card to-card shadow-[0_0_0_1px_rgba(56,189,248,0.06)]">
        <CardContent className="grid gap-4 p-4 sm:grid-cols-[1fr_auto] sm:items-center sm:p-5">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="info">guided setup</Badge>
              <Badge tone="success">vpn-first</Badge>
              <Badge tone="neutral">Jellyfin + downloads</Badge>
            </div>
            <div>
              <h2 className="font-mono text-lg font-semibold text-foreground">Media server quickstart</h2>
              <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
                Create the media stack in one run: provision folders, install the bundle, start Compose, then seed app
                folders and first-run config.
              </p>
            </div>
            <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
              <span className="inline-flex items-center gap-2 rounded-md border border-border/70 bg-background/50 px-2 py-1.5">
                <FolderTree aria-hidden="true" className="h-3.5 w-3.5 text-info" />
                Media folders
              </span>
              <span className="inline-flex items-center gap-2 rounded-md border border-border/70 bg-background/50 px-2 py-1.5">
                <ShieldCheck aria-hidden="true" className="h-3.5 w-3.5 text-success" />
                VPN networking
              </span>
              <span className="inline-flex items-center gap-2 rounded-md border border-border/70 bg-background/50 px-2 py-1.5">
                <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5 text-primary" />
                Seeded apps
              </span>
            </div>
          </div>
          <Button
            className="gap-2 sm:min-w-40"
            data-media-quickstart-open
            disabled={quickstart.status === "running"}
            onClick={() => setQuickstart((current) => ({ ...current, open: true, status: "idle", error: null }))}
            size="lg"
            variant="info"
          >
            <Rocket aria-hidden="true" className="h-4 w-4" />
            Quickstart
          </Button>
        </CardContent>
      </Card>

      {isLoading ? (
        <Card aria-live="polite" role="status">
          <CardContent className="flex min-h-[14rem] items-center justify-center p-6 text-sm text-muted-foreground">
            Loading catalog...
          </CardContent>
        </Card>
      ) : null}

      {!isLoading && items.length ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((item) => (
            <Card className="flex flex-col transition-colors duration-200 hover:border-primary/25" key={item.id}>
              <CardContent className="flex flex-1 flex-col gap-3 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold">{item.name}</p>
                    <p className="line-clamp-2 text-xs text-muted-foreground">{item.description}</p>
                  </div>
                  {item.installedStacks.length ? <StatusBadge label="installed" tone="success" /> : null}
                </div>
                {item.requires.length ? (
                  <div className="flex flex-wrap gap-1.5">
                    {item.requires.map((req) => (
                      <Badge key={req} tone="warning">
                        requires: {req}
                      </Badge>
                    ))}
                  </div>
                ) : null}
                {item.installedStacks.length ? (
                  <div className="space-y-1.5" role="list" aria-label={`${item.name} installations`}>
                    {item.installedStacks.map((stack) => {
                      const key = installationKey(item.id, stack);
                      const isConfirming = confirmRemoveInstallation === key;
                      const isPending = pendingInstallation === key;
                      return (
                        <div
                          className="flex min-h-11 items-center justify-between gap-2 rounded-md border border-border/70 bg-muted/30 px-2"
                          key={stack}
                          role="listitem"
                        >
                          <Badge className="max-w-32 truncate" title={stack} tone="success">
                            {stack}
                          </Badge>
                          {isConfirming ? (
                            <span className="flex items-center gap-1.5">
                              <Button
                                className="border-danger/30 bg-danger/10 px-3 text-xs text-danger hover:bg-danger/15"
                                data-confirm-remove={item.id}
                                data-stack={stack}
                                disabled={isPending}
                                onClick={() => void onRemove(item, stack)}
                                variant="outline"
                              >
                                {isPending ? "Removing..." : "Confirm"}
                              </Button>
                              <Button
                                aria-label={`Cancel removing ${item.name} from ${stack}`}
                                className="px-3 text-xs"
                                onClick={() => setConfirmRemoveInstallation(null)}
                                variant="ghost"
                              >
                                Cancel
                              </Button>
                            </span>
                          ) : (
                            <Button
                              aria-label={`Remove ${item.name} from ${stack}`}
                              className="w-11 px-0"
                              data-catalog-action="remove"
                              data-item={item.id}
                              data-stack={stack}
                              disabled={Boolean(pendingInstallation)}
                              onClick={() => setConfirmRemoveInstallation(key)}
                              title={`Remove from ${stack}`}
                              variant="ghost"
                            >
                              <Trash2 aria-hidden="true" className="h-4 w-4" />
                            </Button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : null}
                <div className="mt-auto flex flex-wrap gap-2">
                  <Button
                    className="px-3 text-xs sm:text-sm"
                    data-catalog-action="install"
                    data-item={item.id}
                    disabled={Boolean(pendingInstallation)}
                    onClick={() => void onOpenInstall(item)}
                  >
                    Install
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : null}

      {!isLoading && !items.length && !error ? (
        <Card>
          <CardContent className="flex min-h-[10rem] items-center justify-center p-6 text-sm text-muted-foreground">
            No catalog items found.
          </CardContent>
        </Card>
      ) : null}

      {installModal.open ? (
        <ModalOverlay onClose={() => setInstallModal(EMPTY_INSTALL)}>
          <Card
            aria-labelledby="v2-catalog-install-title"
            aria-modal="true"
            className="flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden"
            id="v2-catalog-install-modal"
            role="dialog"
          >
            <CardHeader className="flex flex-row items-start justify-between gap-3 border-b border-border/70 p-4 sm:p-5">
              <div className="space-y-1">
                <CardTitle className="text-base sm:text-lg" id="v2-catalog-install-title">
                  Install {installModal.itemName}
                </CardTitle>
                <CardDescription>Confirm configuration before deploying.</CardDescription>
              </div>
              <Button id="v2-catalog-install-close" onClick={() => setInstallModal(EMPTY_INSTALL)} variant="outline">
                Close
              </Button>
            </CardHeader>
            <CardContent className="space-y-3 overflow-auto p-4">
              {installModal.status === "loading" ? (
                <p className="text-sm text-muted-foreground">Loading options...</p>
              ) : installModal.status === "error" ? (
                <p className="text-sm text-danger">{installModal.error}</p>
              ) : (
                <>
                  <label className="block space-y-1">
                    <span className="text-xs uppercase tracking-wide text-muted-foreground">Target stack</span>
                    <select
                      className="min-h-11 w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      data-install-target
                      onChange={(event) =>
                        setInstallModal((current) => ({ ...current, targetStack: event.target.value }))
                      }
                      value={installModal.targetStack}
                    >
                      <option value="new">Create new stack</option>
                      {availableStacks.map((stack) => {
                        const alreadyInstalled = modalItem?.installedStacks.includes(stack) ?? false;
                        return (
                          <option disabled={alreadyInstalled} key={stack} value={stack}>
                            {stack}{alreadyInstalled ? " (installed)" : ""}
                          </option>
                        );
                      })}
                    </select>
                  </label>
                  {installModal.targetStack === "new" ? (
                    <label className="block space-y-1">
                      <span className="text-xs uppercase tracking-wide text-muted-foreground">New stack name</span>
                      <input
                        className="min-h-11 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm"
                        data-install-stack-name
                        onChange={(event) =>
                          setInstallModal((current) => ({ ...current, newStackName: event.target.value }))
                        }
                        spellCheck={false}
                        value={installModal.newStackName}
                      />
                    </label>
                  ) : null}
                  {installModal.fields.length ? (
                    installModal.fields.map((field) => (
                      <label className="block space-y-1" key={field.key}>
                        <span className="text-xs uppercase tracking-wide text-muted-foreground">{field.label}</span>
                        <input
                          className="w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm"
                          data-install-field={field.key}
                          onChange={(event) =>
                            setInstallModal((current) => ({
                              ...current,
                              values: { ...current.values, [field.key]: event.target.value },
                            }))
                          }
                          spellCheck={false}
                          value={installModal.values[field.key] ?? ""}
                        />
                      </label>
                    ))
                  ) : (
                    <p className="text-sm text-muted-foreground">No configuration required.</p>
                  )}
                  {installModal.error ? (
                    <p className="text-sm text-danger" id="v2-catalog-install-error">
                      {installModal.error}
                    </p>
                  ) : null}
                  <Button
                    disabled={
                      installModal.saving
                      || (installModal.targetStack === "new" && !installModal.newStackName.trim())
                    }
                    id="v2-catalog-install-submit"
                    onClick={() => void submitInstall()}
                  >
                    {installModal.saving ? (
                      <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                    ) : null}
                    {installModal.saving ? "Installing..." : "Install"}
                  </Button>
                </>
              )}
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}

      {quickstart.open ? (
        <ModalOverlay
          onClose={quickstart.status === "running" ? () => undefined : () => setQuickstart(EMPTY_QUICKSTART)}
        >
          <Card
            aria-labelledby="v2-media-quickstart-title"
            aria-modal="true"
            className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden"
            id="v2-media-quickstart-modal"
            role="dialog"
          >
            <CardHeader className="flex flex-row items-start justify-between gap-3 border-b border-border/70 p-4 sm:p-5">
              <div className="space-y-1">
                <CardTitle className="text-base sm:text-lg" id="v2-media-quickstart-title">
                  Media server quickstart
                </CardTitle>
                <CardDescription>Build the media stack with VPN-first defaults.</CardDescription>
              </div>
              <Button
                disabled={quickstart.status === "running"}
                id="v2-media-quickstart-close"
                onClick={() => setQuickstart(EMPTY_QUICKSTART)}
                variant="outline"
              >
                Close
              </Button>
            </CardHeader>
            <CardContent className="space-y-4 overflow-auto p-4">
              {quickstart.status === "running" || quickstart.status === "success" || quickstart.status === "error" ? (
                <>
                  <div
                    aria-live={quickstart.status === "error" ? "assertive" : "polite"}
                    className={cn(
                      "rounded-md border p-3 text-sm",
                      quickstart.status === "error"
                        ? "border-danger/30 text-danger"
                        : quickstart.status === "success"
                          ? "border-success/30 text-success"
                          : "border-info/30 text-info",
                    )}
                    role="status"
                  >
                    {quickstart.status === "running"
                      ? "Quickstart is running..."
                      : quickstart.status === "success"
                        ? `Media quickstart completed for ${quickstart.stackName}`
                        : quickstart.error}
                  </div>
                  <pre
                    className="max-h-72 overflow-auto rounded-md border border-border bg-black/30 p-3 font-mono text-xs leading-5 text-muted-foreground"
                    data-media-quickstart-log
                  >
                    {quickstart.lines.join("\n")}
                  </pre>
                </>
              ) : (
                <>
                  <label className="block space-y-1">
                    <span className="text-xs uppercase tracking-wide text-muted-foreground">Stack name</span>
                    <input
                      className="min-h-11 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      data-media-quickstart-stack
                      onChange={(event) =>
                        setQuickstart((current) => ({
                          ...current,
                          stackName: event.target.value,
                          error: null,
                        }))
                      }
                      spellCheck={false}
                      value={quickstart.stackName}
                    />
                  </label>
                  <p className="text-sm text-muted-foreground">
                    This uses the media bundle with VPN enabled. Non-VPN mode is not exposed yet because the current
                    catalog definitions depend on VPN networking.
                  </p>
                  {quickstart.error ? (
                    <p className="text-sm text-danger" id="v2-media-quickstart-error">
                      {quickstart.error}
                    </p>
                  ) : null}
                  <Button className="gap-2" data-media-quickstart-start onClick={() => void submitQuickstart()}>
                    <Rocket aria-hidden="true" className="h-4 w-4" />
                    Start quickstart
                  </Button>
                </>
              )}
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}
    </section>
  );
}
