import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Loader2, RefreshCw, TriangleAlert } from "lucide-react";

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
  error: string | null;
  saving: boolean;
}

const EMPTY_INSTALL: InstallModalState = {
  open: false,
  itemId: "",
  itemName: "",
  status: "idle",
  fields: [],
  values: {},
  error: null,
  saving: false,
};

function getErrorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : "Unable to complete the request";
}

export function CatalogPage() {
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState("Never");
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [confirmRemoveId, setConfirmRemoveId] = useState<string | null>(null);
  const [installModal, setInstallModal] = useState<InstallModalState>(EMPTY_INSTALL);
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
      setItems(next);
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
    async (item: CatalogItem) => {
      setConfirmRemoveId(null);
      setPendingId(item.id);
      try {
        await removeCatalogItem(item.id);
        if (isMountedRef.current) {
          setActionNotice({ tone: "success", message: `Removed ${item.name}` });
          await loadCatalog("manual");
        }
      } catch (caughtError) {
        if (isMountedRef.current) {
          setActionNotice({ tone: "error", message: getErrorMessage(caughtError) });
        }
      } finally {
        if (isMountedRef.current) {
          setPendingId(null);
        }
      }
    },
    [loadCatalog],
  );

  const onOpenInstall = useCallback(async (item: CatalogItem) => {
    setInstallModal({ ...EMPTY_INSTALL, open: true, itemId: item.id, itemName: item.name, status: "loading" });
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
  }, []);

  const submitInstall = useCallback(async () => {
    setInstallModal((current) => ({ ...current, saving: true, error: null }));
    try {
      await installCatalogItem(installModal.itemId, installModal.values);
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

  useEffect(() => {
    isMountedRef.current = true;
    void loadCatalog("initial");
    const intervalId = window.setInterval(() => void loadCatalog("poll"), POLL_INTERVAL_MS);
    return () => {
      isMountedRef.current = false;
      window.clearInterval(intervalId);
    };
  }, [loadCatalog]);

  const installedCount = items.filter((item) => item.installed).length;

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
        description={`${installedCount} installed · ${items.length - installedCount} available`}
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
                  {item.installed ? <StatusBadge label="installed" tone="success" /> : null}
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
                <div className="mt-auto flex flex-wrap gap-2">
                  {item.installed ? (
                    confirmRemoveId === item.id ? (
                      <span className="flex items-center gap-1.5">
                        <Button
                          className="border-danger/30 bg-danger/10 text-danger hover:bg-danger/15 text-xs sm:text-sm"
                          data-confirm-remove={item.id}
                          disabled={pendingId === item.id}
                          onClick={() => void onRemove(item)}
                          size="sm"
                          variant="outline"
                        >
                          {pendingId === item.id ? "Removing..." : "Confirm remove"}
                        </Button>
                        <Button onClick={() => setConfirmRemoveId(null)} size="sm" variant="outline">
                          Cancel
                        </Button>
                      </span>
                    ) : (
                      <Button
                        className="text-xs sm:text-sm"
                        data-catalog-action="remove"
                        data-item={item.id}
                        disabled={Boolean(pendingId)}
                        onClick={() => setConfirmRemoveId(item.id)}
                        size="sm"
                        variant="outline"
                      >
                        Remove
                      </Button>
                    )
                  ) : (
                    <Button
                      className="text-xs sm:text-sm"
                      data-catalog-action="install"
                      data-item={item.id}
                      disabled={Boolean(pendingId)}
                      onClick={() => void onOpenInstall(item)}
                      size="sm"
                    >
                      Install
                    </Button>
                  )}
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
                    disabled={installModal.saving}
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
    </section>
  );
}
