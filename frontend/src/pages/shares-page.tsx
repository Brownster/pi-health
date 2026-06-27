import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Loader2, Plus, RefreshCw, TriangleAlert } from "lucide-react";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import { PageHeader } from "@/components/ui/page-header";
import {
  type PluginShares,
  type ShareEntry,
  addShare,
  deleteShare,
  fetchShares,
  toggleShare,
  updateShare,
} from "@/lib/shares";
import { fetchPlugins } from "@/lib/storage-plugins";
import { formatClockTime } from "@/lib/format";
import { cn } from "@/lib/utils";

interface ActionNotice {
  message: string;
  tone: "success" | "error";
}

type SaveStatus = "idle" | "saving" | "error";

interface ShareModalState {
  open: boolean;
  mode: "add" | "edit";
  pluginId: string;
  pluginName: string;
  shareName: string | null;
  text: string;
  status: SaveStatus;
  error: string | null;
}

const EMPTY_SHARE_MODAL: ShareModalState = {
  open: false,
  mode: "add",
  pluginId: "",
  pluginName: "",
  shareName: null,
  text: "",
  status: "idle",
  error: null,
};

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "Unable to complete the request";
}

export function SharesPage() {
  const [pluginShares, setPluginShares] = useState<PluginShares[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState("Never");
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [confirmKey, setConfirmKey] = useState<string | null>(null);
  const [shareModal, setShareModal] = useState<ShareModalState>(EMPTY_SHARE_MODAL);
  const isMountedRef = useRef(true);

  const loadAll = useCallback(async (reason: "initial" | "manual") => {
    if (reason === "initial") {
      setIsLoading(true);
    } else {
      setIsRefreshing(true);
    }
    try {
      const plugins = await fetchPlugins();
      // No explicit share-capability flag in the list payload; treat "shares" category plugins
      // as share providers (documented heuristic).
      const sharePlugins = plugins.filter((plugin) => plugin.category.toLowerCase().includes("share"));
      const collected: PluginShares[] = [];
      for (const plugin of sharePlugins) {
        const shares = await fetchShares(plugin.id, plugin.name).catch(() => null);
        if (shares) {
          collected.push(shares);
        }
      }
      if (!isMountedRef.current) {
        return;
      }
      setPluginShares(collected);
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

  const runShareAction = useCallback(
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

  const openAddShare = useCallback((group: PluginShares) => {
    setShareModal({
      open: true,
      mode: "add",
      pluginId: group.pluginId,
      pluginName: group.pluginName,
      shareName: null,
      text: JSON.stringify({ name: "", path: "" }, null, 2),
      status: "idle",
      error: null,
    });
  }, []);

  const openEditShare = useCallback((group: PluginShares, share: ShareEntry) => {
    setShareModal({
      open: true,
      mode: "edit",
      pluginId: group.pluginId,
      pluginName: group.pluginName,
      shareName: share.name,
      text: JSON.stringify({ name: share.name, path: share.path ?? "", enabled: share.enabled }, null, 2),
      status: "idle",
      error: null,
    });
  }, []);

  const saveShareConfig = useCallback(async () => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(shareModal.text) as Record<string, unknown>;
    } catch {
      setShareModal((current) => ({ ...current, status: "error", error: "Share is not valid JSON" }));
      return;
    }
    setShareModal((current) => ({ ...current, status: "saving", error: null }));
    try {
      if (shareModal.mode === "add") {
        await addShare(shareModal.pluginId, parsed);
      } else if (shareModal.shareName) {
        await updateShare(shareModal.pluginId, shareModal.shareName, parsed);
      }
      if (!isMountedRef.current) {
        return;
      }
      setShareModal(EMPTY_SHARE_MODAL);
      setActionNotice({
        tone: "success",
        message: shareModal.mode === "add" ? "Share created" : "Share updated",
      });
      await loadAll("manual");
    } catch (caughtError) {
      if (isMountedRef.current) {
        setShareModal((current) => ({ ...current, status: "error", error: getErrorMessage(caughtError) }));
      }
    }
  }, [shareModal, loadAll]);

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
          <Button
            className="gap-2"
            disabled={isRefreshing}
            onClick={() => void loadAll("manual")}
            variant="secondary"
          >
            <RefreshCw aria-hidden="true" className={cn("h-4 w-4", isRefreshing ? "animate-spin" : "")} />
            {isRefreshing ? "refreshing" : "refresh"}
          </Button>
        }
        description={`${pluginShares.reduce((total, group) => total + group.shares.length, 0)} shares · synced ${lastUpdated}`}
        status={
          <StatusBadge
            label={`${pluginShares.reduce((total, group) => total + group.shares.filter((share) => share.enabled).length, 0)} enabled`}
            tone="success"
          />
        }
        title="network_shares"
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

      {error ? (
        <Card aria-live="polite" className="border-warning/30" role="status">
          <CardContent className="flex items-center gap-2 p-4 text-sm text-warning">
            <TriangleAlert aria-hidden="true" className="h-4 w-4" />
            {error}
          </CardContent>
        </Card>
      ) : null}

      {isLoading ? (
        <Card aria-live="polite" role="status">
          <CardContent className="flex min-h-[14rem] items-center justify-center gap-2 p-6 text-sm text-muted-foreground">
            <Activity aria-hidden="true" className="h-4 w-4 animate-pulse text-primary" />
            Loading shares...
          </CardContent>
        </Card>
      ) : null}

      {!isLoading && !pluginShares.length ? (
        <Card>
          <CardContent className="flex min-h-[10rem] items-center justify-center p-6 text-sm text-muted-foreground">
            No share plugins configured.
          </CardContent>
        </Card>
      ) : null}

      {!isLoading
        ? pluginShares.map((group) => (
            <Card className="transition-colors duration-200 hover:border-primary/25" key={group.pluginId}>
              <CardHeader className="flex flex-row items-start justify-between gap-3">
                <div className="space-y-1">
                  <CardTitle className="text-base sm:text-lg">{group.pluginName}</CardTitle>
                  <CardDescription>{group.message || "Shares"}</CardDescription>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <StatusBadge
                    label={group.serviceRunning ? "running" : "stopped"}
                    tone={group.serviceRunning ? "success" : "neutral"}
                  />
                  <Button
                    className="gap-1.5 text-xs sm:text-sm"
                    data-add-share={group.pluginId}
                    onClick={() => openAddShare(group)}
                    size="sm"
                    variant="outline"
                  >
                    <Plus aria-hidden="true" className="h-3.5 w-3.5" />
                    Add share
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-2">
                {group.shares.length ? (
                  group.shares.map((share: ShareEntry) => {
                    const toggleKey = `toggle:${group.pluginId}:${share.name}`;
                    const deleteKey = `delete:${group.pluginId}:${share.name}`;
                    return (
                      <div
                        className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-muted/20 p-3 text-xs"
                        key={share.name}
                      >
                        <div className="min-w-0">
                          <p className="break-all font-mono text-sm">{share.name}</p>
                          <p className="break-all text-muted-foreground">{share.path || "—"}</p>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusBadge
                            label={share.enabled ? "enabled" : "disabled"}
                            tone={share.enabled ? "success" : "neutral"}
                          />
                          <Button
                            className="text-xs sm:text-sm"
                            data-share={share.name}
                            data-share-action="toggle"
                            disabled={Boolean(pendingKey)}
                            onClick={() =>
                              void runShareAction(
                                toggleKey,
                                () => toggleShare(group.pluginId, share.name),
                                `Toggled ${share.name}`,
                              )
                            }
                            size="sm"
                            variant="outline"
                          >
                            {pendingKey === toggleKey ? (
                              <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
                            ) : null}
                            {share.enabled ? "Disable" : "Enable"}
                          </Button>
                          <Button
                            className="text-xs sm:text-sm"
                            data-edit-share={share.name}
                            disabled={Boolean(pendingKey)}
                            onClick={() => openEditShare(group, share)}
                            size="sm"
                            variant="outline"
                          >
                            Edit
                          </Button>
                          {confirmKey === deleteKey ? (
                            <span className="flex items-center gap-1.5">
                              <Button
                                className="border-danger/30 bg-danger/10 text-danger hover:bg-danger/15 text-xs sm:text-sm"
                                data-confirm-delete-share={share.name}
                                onClick={() =>
                                  void runShareAction(
                                    deleteKey,
                                    () => deleteShare(group.pluginId, share.name),
                                    `Deleted ${share.name}`,
                                  )
                                }
                                size="sm"
                                variant="outline"
                              >
                                Confirm delete
                              </Button>
                              <Button onClick={() => setConfirmKey(null)} size="sm" variant="outline">
                                Cancel
                              </Button>
                            </span>
                          ) : (
                            <Button
                              className="text-xs sm:text-sm"
                              data-delete-share={share.name}
                              disabled={Boolean(pendingKey)}
                              onClick={() => setConfirmKey(deleteKey)}
                              size="sm"
                              variant="outline"
                            >
                              Delete
                            </Button>
                          )}
                        </div>
                      </div>
                    );
                  })
                ) : (
                  <p className="text-sm text-muted-foreground">No shares configured.</p>
                )}
              </CardContent>
            </Card>
          ))
        : null}

      {shareModal.open ? (
        <ModalOverlay onClose={() => setShareModal(EMPTY_SHARE_MODAL)}>
          <Card
            aria-labelledby="v2-share-config-title"
            aria-modal="true"
            className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden"
            id="v2-share-config-modal"
            role="dialog"
          >
            <CardHeader className="flex flex-row items-start justify-between gap-3 border-b border-border/70 p-4 sm:p-5">
              <div className="space-y-1">
                <CardTitle className="text-base sm:text-lg" id="v2-share-config-title">
                  {shareModal.mode === "add" ? "Add" : "Edit"} {shareModal.pluginName} share
                </CardTitle>
                <CardDescription>Share definition as JSON (name + path required).</CardDescription>
              </div>
              <Button id="v2-share-config-close" onClick={() => setShareModal(EMPTY_SHARE_MODAL)} variant="outline">
                Close
              </Button>
            </CardHeader>
            <CardContent className="space-y-3 overflow-auto p-4">
              <textarea
                aria-label="Share definition JSON"
                className="h-[40vh] w-full resize-y rounded-md border border-border bg-muted/25 p-3 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm"
                data-share-config-textarea
                onChange={(event) =>
                  setShareModal((current) => ({ ...current, text: event.target.value, status: "idle", error: null }))
                }
                spellCheck={false}
                value={shareModal.text}
              />
              {shareModal.error ? (
                <p className="text-sm text-danger" id="v2-share-config-error">
                  {shareModal.error}
                </p>
              ) : null}
              <Button
                disabled={shareModal.status === "saving"}
                id="v2-share-config-save"
                onClick={() => void saveShareConfig()}
              >
                {shareModal.status === "saving" ? "Saving..." : "Save share"}
              </Button>
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}
    </section>
  );
}
