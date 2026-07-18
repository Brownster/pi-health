import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Loader2, Plus, RefreshCw, TriangleAlert } from "lucide-react";

import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import { PageHeader } from "@/components/ui/page-header";
import {
  type MediaPathKey,
  type MediaPaths,
  type MountEntry,
  type PluginMounts,
  type StartupPreview,
  MEDIA_PATH_KEYS,
  addMount,
  applyStartupService,
  deleteMount,
  fetchMediaPaths,
  fetchPluginMounts,
  fetchStartupPreview,
  mountEntry,
  saveMediaPaths,
  unmountEntry,
  updateMount,
} from "@/lib/mounts";
import { mapSettledWithConcurrency } from "@/lib/concurrency";
import { fetchPlugins } from "@/lib/storage-plugins";
import { formatClockTime } from "@/lib/format";
import { cn } from "@/lib/utils";

interface ActionNotice {
  message: string;
  tone: "success" | "error";
}

type SaveStatus = "idle" | "saving" | "error";

interface ConfigModalState {
  open: boolean;
  mode: "add" | "edit";
  pluginId: string;
  pluginName: string;
  mountId: string | null;
  text: string;
  status: SaveStatus;
  error: string | null;
}

interface StartupState {
  status: "idle" | "loading" | "ready" | "error";
  preview: StartupPreview | null;
  error: string | null;
  applying: boolean;
  confirming: boolean;
}

const EMPTY_PATHS: MediaPaths = { downloads: "", storage: "", backup: "", config: "" };
const EMPTY_CONFIG_MODAL: ConfigModalState = {
  open: false,
  mode: "add",
  pluginId: "",
  pluginName: "",
  mountId: null,
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

export function MountsPage() {
  const [mediaPaths, setMediaPaths] = useState<MediaPaths>(EMPTY_PATHS);
  const [savingPaths, setSavingPaths] = useState(false);
  const [pathsNotice, setPathsNotice] = useState<ActionNotice | null>(null);
  const [pluginMounts, setPluginMounts] = useState<PluginMounts[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [lastUpdated, setLastUpdated] = useState("Never");
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [confirmKey, setConfirmKey] = useState<string | null>(null);
  const [configModal, setConfigModal] = useState<ConfigModalState>(EMPTY_CONFIG_MODAL);
  const [startup, setStartup] = useState<StartupState>({
    status: "idle",
    preview: null,
    error: null,
    applying: false,
    confirming: false,
  });
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
      const nextWarnings: string[] = [];
      const mountResults = await mapSettledWithConcurrency(plugins, 4, async (plugin) => {
        const mounts = await fetchPluginMounts(plugin.id);
        return mounts === null
          ? null
          : { pluginId: plugin.id, pluginName: plugin.name, mounts };
      });
      const collected: PluginMounts[] = [];
      mountResults.forEach((result, index) => {
        if (result.status === "fulfilled") {
          if (result.value) {
            collected.push(result.value);
          }
        } else {
          nextWarnings.push(
            `${plugins[index].name} mounts unavailable: ${getErrorMessage(result.reason)}`,
          );
        }
      });
      if (!isMountedRef.current) {
        return;
      }
      setMediaPaths(paths);
      setPluginMounts(collected);
      setWarnings(nextWarnings);
      setError(null);
      setLastUpdated(formatClockTime(new Date()));
    } catch (caughtError) {
      if (isMountedRef.current) {
        setWarnings([]);
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

  const openAddMount = useCallback((group: PluginMounts) => {
    setConfigModal({
      open: true,
      mode: "add",
      pluginId: group.pluginId,
      pluginName: group.pluginName,
      mountId: null,
      text: JSON.stringify({}),
      status: "idle",
      error: null,
    });
  }, []);

  const openEditMount = useCallback((group: PluginMounts, mount: MountEntry) => {
    // Seed from known, non-secret fields only — credentials are never echoed back.
    const seed: Record<string, unknown> = { name: mount.name };
    if (mount.mountpoint) {
      seed.mountpoint = mount.mountpoint;
    }
    if (mount.type) {
      seed.type = mount.type;
    }
    setConfigModal({
      open: true,
      mode: "edit",
      pluginId: group.pluginId,
      pluginName: group.pluginName,
      mountId: mount.id,
      text: JSON.stringify(seed, null, 2),
      status: "idle",
      error: null,
    });
  }, []);

  const saveMountConfig = useCallback(async () => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(configModal.text) as Record<string, unknown>;
    } catch {
      setConfigModal((current) => ({ ...current, status: "error", error: "Config is not valid JSON" }));
      return;
    }
    setConfigModal((current) => ({ ...current, status: "saving", error: null }));
    try {
      if (configModal.mode === "add") {
        await addMount(configModal.pluginId, parsed);
      } else if (configModal.mountId) {
        await updateMount(configModal.pluginId, configModal.mountId, parsed);
      }
      if (!isMountedRef.current) {
        return;
      }
      setConfigModal(EMPTY_CONFIG_MODAL);
      setActionNotice({
        tone: "success",
        message: configModal.mode === "add" ? "Mount created" : "Mount updated",
      });
      await loadAll("manual");
    } catch (caughtError) {
      if (isMountedRef.current) {
        setConfigModal((current) => ({ ...current, status: "error", error: getErrorMessage(caughtError) }));
      }
    }
  }, [configModal, loadAll]);

  const loadStartupPreview = useCallback(async () => {
    setStartup((current) => ({ ...current, status: "loading", error: null }));
    try {
      const preview = await fetchStartupPreview();
      if (isMountedRef.current) {
        setStartup((current) => ({ ...current, status: "ready", preview }));
      }
    } catch (caughtError) {
      if (isMountedRef.current) {
        setStartup((current) => ({ ...current, status: "error", error: getErrorMessage(caughtError) }));
      }
    }
  }, []);

  const applyStartup = useCallback(async () => {
    setStartup((current) => ({ ...current, applying: true, confirming: false }));
    try {
      await applyStartupService();
      if (isMountedRef.current) {
        setStartup((current) => ({ ...current, applying: false }));
        setActionNotice({ tone: "success", message: "Startup service applied" });
      }
      await loadStartupPreview();
    } catch (caughtError) {
      if (isMountedRef.current) {
        setStartup((current) => ({ ...current, applying: false }));
        setActionNotice({ tone: "error", message: getErrorMessage(caughtError) });
      }
    }
  }, [loadStartupPreview]);

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
        status={warnings.length ? (
          <StatusBadge label="partial data" tone="warning" />
        ) : (
          <StatusBadge
            label={`${pluginMounts.reduce((total, group) => total + group.mounts.filter((mount) => mount.mounted).length, 0)} mounted`}
            tone="success"
          />
        )}
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

      {warnings.length ? (
        <Card aria-live="polite" className="border-warning/30" role="status">
          <CardContent className="flex items-start gap-2 p-4 text-sm text-warning">
            <TriangleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="space-y-1">
              {warnings.map((warning) => (
                <p key={warning}>{warning}</p>
              ))}
            </div>
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
                <CardHeader className="flex flex-row items-center justify-between gap-3">
                  <CardTitle className="text-base sm:text-lg">{group.pluginName} mounts</CardTitle>
                  <Button
                    className="gap-1.5 text-xs sm:text-sm"
                    data-add-mount={group.pluginId}
                    onClick={() => openAddMount(group)}
                    size="sm"
                    variant="outline"
                  >
                    <Plus aria-hidden="true" className="h-3.5 w-3.5" />
                    Add mount
                  </Button>
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
                          <Button
                            className="text-xs sm:text-sm"
                            data-edit-mount={mount.id}
                            disabled={Boolean(pendingKey)}
                            onClick={() => openEditMount(group, mount)}
                            size="sm"
                            variant="outline"
                          >
                            Edit
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
          ) : warnings.length ? null : (
            <Card>
              <CardContent className="p-6 text-sm text-muted-foreground">
                No remote/local mount plugins configured.
              </CardContent>
            </Card>
          )}

          <Card id="v2-startup-service">
            <CardHeader className="flex flex-row items-start justify-between gap-3">
              <div className="space-y-1">
                <CardTitle className="text-base sm:text-lg">Startup service</CardTitle>
                <CardDescription>Mount-at-boot systemd unit for media paths.</CardDescription>
              </div>
              <Button
                className="gap-2"
                disabled={startup.status === "loading"}
                id="v2-startup-preview"
                onClick={() => void loadStartupPreview()}
                size="sm"
                variant="outline"
              >
                {startup.status === "loading" ? "Loading..." : "Preview"}
              </Button>
            </CardHeader>
            {startup.status === "error" ? (
              <CardContent className="text-sm text-danger">{startup.error}</CardContent>
            ) : startup.preview ? (
              <CardContent className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  <Badge tone={startup.preview.script.changed ? "warning" : "success"}>
                    script {startup.preview.script.changed ? "changed" : "up to date"}
                  </Badge>
                  <Badge tone={startup.preview.service.changed ? "warning" : "success"}>
                    service {startup.preview.service.changed ? "changed" : "up to date"}
                  </Badge>
                </div>
                <pre
                  className="max-h-[24vh] overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-muted/25 p-3 text-xs"
                  id="v2-startup-proposed"
                >
                  {startup.preview.service.proposed || "(no proposed service)"}
                </pre>
                {startup.confirming ? (
                  <span className="flex items-center gap-1.5">
                    <Button
                      className="border-warning/30 bg-warning/10 text-warning hover:bg-warning/15"
                      disabled={startup.applying}
                      id="v2-startup-apply-confirm"
                      onClick={() => void applyStartup()}
                      variant="outline"
                    >
                      {startup.applying ? "Applying..." : "Confirm apply"}
                    </Button>
                    <Button onClick={() => setStartup((c) => ({ ...c, confirming: false }))} variant="outline">
                      Cancel
                    </Button>
                  </span>
                ) : (
                  <Button id="v2-startup-apply" onClick={() => setStartup((c) => ({ ...c, confirming: true }))} variant="outline">
                    Apply
                  </Button>
                )}
              </CardContent>
            ) : null}
          </Card>
        </>
      )}

      {configModal.open ? (
        <ModalOverlay onClose={() => setConfigModal(EMPTY_CONFIG_MODAL)}>
          <Card
            aria-labelledby="v2-mount-config-title"
            aria-modal="true"
            className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden"
            id="v2-mount-config-modal"
            role="dialog"
          >
            <CardHeader className="flex flex-row items-start justify-between gap-3 border-b border-border/70 p-4 sm:p-5">
              <div className="space-y-1">
                <CardTitle className="text-base sm:text-lg" id="v2-mount-config-title">
                  {configModal.mode === "add" ? "Add" : "Edit"} {configModal.pluginName} mount
                </CardTitle>
                <CardDescription>
                  Mount config as JSON. Credential fields are not pre-filled on edit.
                </CardDescription>
              </div>
              <Button id="v2-mount-config-close" onClick={() => setConfigModal(EMPTY_CONFIG_MODAL)} variant="outline">
                Close
              </Button>
            </CardHeader>
            <CardContent className="space-y-3 overflow-auto p-4">
              <textarea
                aria-label="Mount configuration JSON"
                className="h-[40vh] w-full resize-y rounded-md border border-border bg-muted/25 p-3 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm"
                data-mount-config-textarea
                onChange={(event) =>
                  setConfigModal((current) => ({ ...current, text: event.target.value, status: "idle", error: null }))
                }
                spellCheck={false}
                value={configModal.text}
              />
              {configModal.error ? (
                <p className="text-sm text-danger" id="v2-mount-config-error">
                  {configModal.error}
                </p>
              ) : null}
              <Button
                disabled={configModal.status === "saving"}
                id="v2-mount-config-save"
                onClick={() => void saveMountConfig()}
              >
                {configModal.status === "saving" ? "Saving..." : "Save mount"}
              </Button>
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}
    </section>
  );
}
