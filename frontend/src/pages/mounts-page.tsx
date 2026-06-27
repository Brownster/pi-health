import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Loader2, RefreshCw, TriangleAlert } from "lucide-react";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import {
  type MediaPathKey,
  type MediaPaths,
  type MountEntry,
  type PluginMounts,
  MEDIA_PATH_KEYS,
  deleteMount,
  fetchMediaPaths,
  fetchPluginMounts,
  mountEntry,
  saveMediaPaths,
  unmountEntry,
} from "@/lib/mounts";
import { fetchPlugins } from "@/lib/storage-plugins";
import { formatClockTime } from "@/lib/format";
import { cn } from "@/lib/utils";

interface ActionNotice {
  message: string;
  tone: "success" | "error";
}

const EMPTY_PATHS: MediaPaths = { downloads: "", storage: "", backup: "", config: "" };

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "Unable to complete the request";
}

export function MountsPage() {
  const [mediaPaths, setMediaPaths] = useState<MediaPaths>(EMPTY_PATHS);
  const [savingPaths, setSavingPaths] = useState(false);
  const [pathsNotice, setPathsNotice] = useState<ActionNotice | null>(null);
  const [pluginMounts, setPluginMounts] = useState<PluginMounts[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState("Never");
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [confirmKey, setConfirmKey] = useState<string | null>(null);
  const isMountedRef = useRef(true);

  const loadAll = useCallback(async (reason: "initial" | "manual") => {
    if (reason === "initial") {
      setIsLoading(true);
    } else {
      setIsRefreshing(true);
    }
    try {
      const [paths, plugins] = await Promise.all([
        fetchMediaPaths().catch(() => EMPTY_PATHS),
        fetchPlugins(),
      ]);
      const collected: PluginMounts[] = [];
      for (const plugin of plugins) {
        const mounts = await fetchPluginMounts(plugin.id).catch(() => null);
        if (mounts) {
          collected.push({ pluginId: plugin.id, pluginName: plugin.name, mounts });
        }
      }
      if (!isMountedRef.current) {
        return;
      }
      setMediaPaths(paths);
      setPluginMounts(collected);
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

  const onSavePaths = useCallback(async () => {
    setSavingPaths(true);
    setPathsNotice(null);
    try {
      const { warning } = await saveMediaPaths(mediaPaths);
      if (isMountedRef.current) {
        setPathsNotice({
          tone: warning ? "error" : "success",
          message: warning || "Media paths saved",
        });
      }
    } catch (caughtError) {
      if (isMountedRef.current) {
        setPathsNotice({ tone: "error", message: getErrorMessage(caughtError) });
      }
    } finally {
      if (isMountedRef.current) {
        setSavingPaths(false);
      }
    }
  }, [mediaPaths]);

  const runMountAction = useCallback(
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

  useEffect(() => {
    isMountedRef.current = true;
    void loadAll("initial");
    return () => {
      isMountedRef.current = false;
    };
  }, [loadAll]);

  const pathsValid = MEDIA_PATH_KEYS.every((key) => {
    const value = mediaPaths[key];
    return value === "" || value.startsWith("/");
  });

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
        description={`${pluginMounts.reduce((total, group) => total + group.mounts.length, 0)} mounts · synced ${lastUpdated}`}
        status={
          <StatusBadge
            label={`${pluginMounts.reduce((total, group) => total + group.mounts.filter((mount) => mount.mounted).length, 0)} mounted`}
            tone="success"
          />
        }
        title="mount_management"
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
          <CardContent className="flex min-h-[14rem] items-center justify-center gap-2 p-6 text-sm text-muted-foreground">
            <Activity aria-hidden="true" className="h-4 w-4 animate-pulse text-primary" />
            Loading mounts...
          </CardContent>
        </Card>
      ) : (
        <>
          <Card id="v2-media-paths">
            <CardHeader>
              <CardTitle className="text-base sm:text-lg">Media paths</CardTitle>
              <CardDescription>Absolute host paths used by app templates.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {MEDIA_PATH_KEYS.map((key: MediaPathKey) => (
                <label className="block space-y-1" key={key}>
                  <span className="text-xs uppercase tracking-wide text-muted-foreground">{key}</span>
                  <input
                    className="w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm"
                    data-media-path={key}
                    onChange={(event) =>
                      setMediaPaths((current) => ({ ...current, [key]: event.target.value }))
                    }
                    spellCheck={false}
                    value={mediaPaths[key]}
                  />
                </label>
              ))}
              {!pathsValid ? (
                <p className="text-xs text-danger">Paths must be absolute (start with /).</p>
              ) : null}
              {pathsNotice ? (
                <p
                  aria-live="polite"
                  className={cn("text-sm", pathsNotice.tone === "error" ? "text-danger" : "text-success")}
                  id="v2-media-paths-notice"
                  role="status"
                >
                  {pathsNotice.message}
                </p>
              ) : null}
              <Button
                disabled={savingPaths || !pathsValid}
                id="v2-media-paths-save"
                onClick={() => void onSavePaths()}
              >
                {savingPaths ? "Saving..." : "Save media paths"}
              </Button>
            </CardContent>
          </Card>

          {error ? (
            <Card aria-live="polite" className="border-warning/30" role="status">
              <CardContent className="flex items-center gap-2 p-4 text-sm text-warning">
                <TriangleAlert aria-hidden="true" className="h-4 w-4" />
                {error}
              </CardContent>
            </Card>
          ) : null}

          {pluginMounts.length ? (
            pluginMounts.map((group) => (
              <Card className="transition-colors duration-200 hover:border-primary/25" key={group.pluginId}>
                <CardHeader>
                  <CardTitle className="text-base sm:text-lg">{group.pluginName} mounts</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {group.mounts.map((mount: MountEntry) => {
                    const toggleKey = `toggle:${group.pluginId}:${mount.id}`;
                    const deleteKey = `delete:${group.pluginId}:${mount.id}`;
                    return (
                      <div
                        className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-muted/20 p-3 text-xs"
                        key={mount.id}
                      >
                        <div className="min-w-0">
                          <p className="break-all font-mono text-sm">{mount.name}</p>
                          <p className="text-muted-foreground">
                            {mount.mountpoint || "no mountpoint"}
                            {mount.type ? ` · ${mount.type}` : ""}
                          </p>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusBadge
                            label={mount.mounted ? "mounted" : "unmounted"}
                            tone={mount.mounted ? "success" : "neutral"}
                          />
                          <Button
                            className={cn(
                              "text-xs sm:text-sm",
                              mount.mounted
                                ? "border-warning/30 bg-warning/10 text-warning hover:bg-warning/15"
                                : "border-success/30 bg-success/10 text-success hover:bg-success/15",
                            )}
                            data-mount-action={mount.mounted ? "unmount" : "mount"}
                            data-mount={mount.id}
                            disabled={Boolean(pendingKey)}
                            onClick={() =>
                              void runMountAction(
                                toggleKey,
                                () =>
                                  mount.mounted
                                    ? unmountEntry(group.pluginId, mount.id)
                                    : mountEntry(group.pluginId, mount.id),
                                `${mount.mounted ? "Unmounted" : "Mounted"} ${mount.name}`,
                              )
                            }
                            size="sm"
                            variant="outline"
                          >
                            {pendingKey === toggleKey ? (
                              <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
                            ) : null}
                            {mount.mounted ? "Unmount" : "Mount"}
                          </Button>
                          {confirmKey === deleteKey ? (
                            <span className="flex items-center gap-1.5">
                              <Button
                                className="border-danger/30 bg-danger/10 text-danger hover:bg-danger/15 text-xs sm:text-sm"
                                data-confirm-delete-mount={mount.id}
                                onClick={() =>
                                  void runMountAction(
                                    deleteKey,
                                    () => deleteMount(group.pluginId, mount.id),
                                    `Deleted ${mount.name}`,
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
                              data-delete-mount={mount.id}
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
                  })}
                </CardContent>
              </Card>
            ))
          ) : (
            <Card>
              <CardContent className="p-6 text-sm text-muted-foreground">
                No remote/local mount plugins configured.
              </CardContent>
            </Card>
          )}
        </>
      )}
    </section>
  );
}
