import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { Activity, Boxes, Loader2, Plus, RefreshCw, Terminal, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import {
  type PluginCommand,
  type PluginDetail,
  type PluginRecovery,
  type StoragePlugin,
  fetchPluginDetail,
  fetchPluginLatestLog,
  fetchPluginRecovery,
  fetchPlugins,
  installPlugin,
  isPoolPlugin,
  removePlugin,
  savePluginConfig,
  streamPluginCommand,
  togglePlugin,
} from "@/lib/storage-plugins";
import { formatClockTime } from "@/lib/format";
import { cn } from "@/lib/utils";

type StorageTab = "plugins" | "pools";
type AsyncStatus = "idle" | "loading" | "ready" | "error";

interface ActionNotice {
  message: string;
  tone: "info" | "success" | "error";
}

interface CommandConsole {
  running: boolean;
  commandId: string | null;
  lines: string[];
  error: string | null;
}

type SaveStatus = "idle" | "saving" | "saved" | "error";

interface ConfigEditor {
  text: string;
  status: SaveStatus;
  error: string | null;
  details: string[];
}

interface DetailModalState {
  open: boolean;
  pluginId: string;
  name: string;
  status: AsyncStatus;
  detail: PluginDetail | null;
  recovery: PluginRecovery | null;
  log: string | null;
  error: string | null;
  command: CommandConsole;
  config: ConfigEditor;
}

interface InstallModalState {
  open: boolean;
  type: string;
  source: string;
  id: string;
  entry: string;
  class_name: string;
  status: SaveStatus;
  error: string | null;
}

const EMPTY_CONFIG: ConfigEditor = { text: "", status: "idle", error: null, details: [] };
const EMPTY_INSTALL: InstallModalState = {
  open: false,
  type: "github",
  source: "",
  id: "",
  entry: "",
  class_name: "",
  status: "idle",
  error: null,
};

const EMPTY_COMMAND: CommandConsole = { running: false, commandId: null, lines: [], error: null };

function getStatusTone(plugin: StoragePlugin): string {
  if (!plugin.enabled) {
    return "bg-slate-500/15 text-slate-300 border-slate-500/40";
  }
  if (plugin.status === "active" || plugin.status === "ok") {
    return "bg-emerald-500/15 text-emerald-300 border-emerald-500/40";
  }
  if (plugin.status === "missing" || plugin.status === "error") {
    return "bg-rose-500/15 text-rose-300 border-rose-500/40";
  }
  return "bg-amber-500/15 text-amber-300 border-amber-500/40";
}

function getNoticeToneClass(tone: ActionNotice["tone"]): string {
  if (tone === "success") return "border-emerald-500/40 text-emerald-300";
  if (tone === "error") return "border-rose-500/40 text-rose-300";
  return "border-sky-500/40 text-sky-300";
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "Unable to complete the request";
}

function PluginCard({
  plugin,
  pending,
  confirmingRemove,
  onToggle,
  onDetails,
  onRemoveRequest,
  onRemoveConfirm,
  onRemoveCancel,
}: {
  plugin: StoragePlugin;
  pending: boolean;
  confirmingRemove: boolean;
  onToggle: (plugin: StoragePlugin) => void;
  onDetails: (plugin: StoragePlugin) => void;
  onRemoveRequest: (id: string) => void;
  onRemoveConfirm: (plugin: StoragePlugin) => void;
  onRemoveCancel: () => void;
}) {
  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">{plugin.name}</p>
            <p className="line-clamp-2 text-xs text-muted-foreground">{plugin.description || plugin.id}</p>
          </div>
          <span
            className={cn(
              "shrink-0 rounded-full border px-2 py-1 text-xs font-medium",
              getStatusTone(plugin),
            )}
          >
            {plugin.enabled ? plugin.status : "disabled"}
          </span>
        </div>

        <div className="flex flex-wrap gap-2 text-xs">
          <span className={cn("rounded px-1.5 py-0.5 font-mono", plugin.installed ? "bg-emerald-500/10 text-emerald-300" : "bg-slate-500/10 text-slate-300")}>
            {plugin.installed ? "installed" : "not installed"}
          </span>
          {plugin.status_message ? (
            <span className="text-muted-foreground">{plugin.status_message}</span>
          ) : null}
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            aria-label={`${plugin.enabled ? "Disable" : "Enable"} ${plugin.name}`}
            className={cn(
              "gap-1.5 text-xs sm:text-sm",
              plugin.enabled
                ? "border-amber-500/40 text-amber-300 hover:bg-amber-500/15"
                : "border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/15",
            )}
            data-plugin={plugin.id}
            data-plugin-action={plugin.enabled ? "disable" : "enable"}
            disabled={pending}
            onClick={() => onToggle(plugin)}
            size="sm"
            variant="outline"
          >
            {pending ? <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" /> : null}
            {plugin.enabled ? "Disable" : "Enable"}
          </Button>
          <Button
            aria-label={`Details ${plugin.name}`}
            className="gap-1.5 text-xs sm:text-sm"
            data-plugin={plugin.id}
            data-plugin-action="details"
            disabled={pending}
            onClick={() => onDetails(plugin)}
            size="sm"
            variant="outline"
          >
            Details
          </Button>
          {plugin.type !== "builtin" ? (
            confirmingRemove ? (
              <span className="flex items-center gap-1.5">
                <Button
                  className="border-rose-500/40 text-rose-300 hover:bg-rose-500/15 text-xs sm:text-sm"
                  data-confirm-remove={plugin.id}
                  onClick={() => onRemoveConfirm(plugin)}
                  size="sm"
                  variant="outline"
                >
                  Confirm remove
                </Button>
                <Button onClick={onRemoveCancel} size="sm" variant="outline">
                  Cancel
                </Button>
              </span>
            ) : (
              <Button
                aria-label={`Remove ${plugin.name}`}
                className="text-xs sm:text-sm"
                data-plugin={plugin.id}
                data-plugin-action="remove"
                disabled={pending}
                onClick={() => onRemoveRequest(plugin.id)}
                size="sm"
                variant="outline"
              >
                Remove
              </Button>
            )
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

export function StoragePage() {
  const location = useLocation();
  const [plugins, setPlugins] = useState<StoragePlugin[]>([]);
  const [tab, setTab] = useState<StorageTab>(location.pathname.includes("/pools") ? "pools" : "plugins");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState("Never");
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [confirmRemoveId, setConfirmRemoveId] = useState<string | null>(null);
  const [detailModal, setDetailModal] = useState<DetailModalState>({
    open: false,
    pluginId: "",
    name: "",
    status: "idle",
    detail: null,
    recovery: null,
    log: null,
    error: null,
    command: EMPTY_COMMAND,
    config: EMPTY_CONFIG,
  });
  const [installModal, setInstallModal] = useState<InstallModalState>(EMPTY_INSTALL);
  const isMountedRef = useRef(true);

  const loadPlugins = useCallback(async (reason: "initial" | "manual") => {
    if (reason === "initial") {
      setIsLoading(true);
    } else {
      setIsRefreshing(true);
    }
    try {
      const next = await fetchPlugins();
      if (!isMountedRef.current) {
        return;
      }
      setPlugins(next);
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

  const onToggle = useCallback(
    async (plugin: StoragePlugin) => {
      if (pendingId) {
        return;
      }
      setPendingId(plugin.id);
      try {
        await togglePlugin(plugin.id, !plugin.enabled);
        if (isMountedRef.current) {
          setActionNotice({
            tone: "success",
            message: `${plugin.name} ${plugin.enabled ? "disabled" : "enabled"}`,
          });
          await loadPlugins("manual");
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
    [loadPlugins, pendingId],
  );

  const onRemoveConfirm = useCallback(
    async (plugin: StoragePlugin) => {
      setConfirmRemoveId(null);
      setPendingId(plugin.id);
      try {
        await removePlugin(plugin.id);
        if (isMountedRef.current) {
          setActionNotice({ tone: "success", message: `Removed ${plugin.name}` });
          await loadPlugins("manual");
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
    [loadPlugins],
  );

  const onDetails = useCallback(async (plugin: StoragePlugin) => {
    setDetailModal({
      open: true,
      pluginId: plugin.id,
      name: plugin.name,
      status: "loading",
      detail: null,
      recovery: null,
      log: null,
      error: null,
      command: EMPTY_COMMAND,
      config: EMPTY_CONFIG,
    });

    try {
      const [detail, recovery, log] = await Promise.all([
        fetchPluginDetail(plugin.id),
        fetchPluginRecovery(plugin.id).catch(() => ({ supported: false, data: null }) as PluginRecovery),
        fetchPluginLatestLog(plugin.id).catch(() => null),
      ]);
      if (!isMountedRef.current) {
        return;
      }
      setDetailModal((current) =>
        current.pluginId === plugin.id && current.open
          ? {
              ...current,
              status: "ready",
              detail,
              recovery,
              log,
              config: { ...EMPTY_CONFIG, text: JSON.stringify(detail.config ?? {}, null, 2) },
            }
          : current,
      );
    } catch (caughtError) {
      if (!isMountedRef.current) {
        return;
      }
      setDetailModal((current) =>
        current.pluginId === plugin.id && current.open
          ? { ...current, status: "error", error: getErrorMessage(caughtError) }
          : current,
      );
    }
  }, []);

  const closeDetails = useCallback(() => {
    setDetailModal((current) => ({ ...current, open: false }));
  }, []);

  const runCommand = useCallback(async (pluginId: string, command: PluginCommand) => {
    setDetailModal((current) => ({
      ...current,
      command: { running: true, commandId: command.id, lines: [], error: null },
    }));

    try {
      await streamPluginCommand(pluginId, command.id, {}, (event) => {
        if (!isMountedRef.current) {
          return;
        }
        if (event.type === "output" && typeof event.line === "string") {
          const line = event.line;
          setDetailModal((current) => ({ ...current, command: { ...current.command, lines: [...current.command.lines, line] } }));
        } else if (event.type === "complete") {
          const summary = `— ${event.success ? "completed" : "failed"}${event.message ? `: ${event.message}` : ""}`;
          setDetailModal((current) => ({
            ...current,
            command: { ...current.command, running: false, lines: [...current.command.lines, summary] },
          }));
        } else if (event.type === "error") {
          setDetailModal((current) => ({ ...current, command: { ...current.command, running: false, error: event.error ?? "Command error" } }));
        }
      });
      if (isMountedRef.current) {
        setDetailModal((current) => ({ ...current, command: { ...current.command, running: false } }));
      }
    } catch (caughtError) {
      if (isMountedRef.current) {
        setDetailModal((current) => ({
          ...current,
          command: { ...current.command, running: false, error: getErrorMessage(caughtError) },
        }));
      }
    }
  }, []);

  const saveConfig = useCallback(async (pluginId: string, text: string) => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(text) as Record<string, unknown>;
    } catch {
      setDetailModal((current) => ({
        ...current,
        config: { ...current.config, status: "error", error: "Config is not valid JSON", details: [] },
      }));
      return;
    }

    setDetailModal((current) => ({ ...current, config: { ...current.config, status: "saving", error: null, details: [] } }));
    const result = await savePluginConfig(pluginId, parsed);
    if (!isMountedRef.current) {
      return;
    }
    if (result.ok) {
      setDetailModal((current) => ({ ...current, config: { ...current.config, status: "saved", error: null, details: [] } }));
      setActionNotice({ tone: "success", message: "Plugin config saved" });
    } else {
      setDetailModal((current) => ({
        ...current,
        config: { ...current.config, status: "error", error: result.error, details: result.details },
      }));
    }
  }, []);

  const installNewPlugin = useCallback(async () => {
    setInstallModal((current) => ({ ...current, status: "saving", error: null }));
    try {
      await installPlugin({
        type: installModal.type,
        source: installModal.source,
        id: installModal.id || undefined,
        entry: installModal.entry || undefined,
        class_name: installModal.class_name || undefined,
      });
      if (!isMountedRef.current) {
        return;
      }
      setInstallModal(EMPTY_INSTALL);
      setActionNotice({ tone: "success", message: "Plugin installed" });
      await loadPlugins("manual");
    } catch (caughtError) {
      if (isMountedRef.current) {
        setInstallModal((current) => ({ ...current, status: "error", error: getErrorMessage(caughtError) }));
      }
    }
  }, [installModal, loadPlugins]);

  useEffect(() => {
    isMountedRef.current = true;
    void loadPlugins("initial");
    return () => {
      isMountedRef.current = false;
    };
  }, [loadPlugins]);

  // Both /v2/plugins and /v2/pools render this component, so keep the active tab in
  // sync with the route when navigating between them inside the v2 shell.
  useEffect(() => {
    setTab(location.pathname.includes("/pools") ? "pools" : "plugins");
  }, [location.pathname]);

  useEffect(() => {
    if (!actionNotice || actionNotice.tone === "error") {
      return undefined;
    }
    const timeoutId = window.setTimeout(() => setActionNotice(null), 4500);
    return () => window.clearTimeout(timeoutId);
  }, [actionNotice]);

  const visiblePlugins = tab === "pools" ? plugins.filter((plugin) => isPoolPlugin(plugin)) : plugins;

  return (
    <section className="space-y-4 sm:space-y-6">
      <Card>
        <CardHeader className="space-y-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0 space-y-1">
              <CardTitle className="flex items-center gap-2 text-lg sm:text-xl">
                <Boxes aria-hidden="true" className="h-5 w-5 text-primary" />
                Storage
              </CardTitle>
              <CardDescription>Storage plugins and pools.</CardDescription>
            </div>
            <span className="inline-flex min-h-11 items-center rounded-md border border-border bg-muted/70 px-3 text-xs text-muted-foreground">
              Last updated: {lastUpdated}
            </span>
          </div>

          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
            <div aria-label="Storage tabs" className="flex flex-wrap items-center gap-2" role="group">
              {(["plugins", "pools"] as StorageTab[]).map((item) => (
                <Button
                  aria-pressed={tab === item}
                  data-storage-tab={item}
                  key={item}
                  onClick={() => setTab(item)}
                  variant={tab === item ? "default" : "outline"}
                >
                  {item === "plugins" ? "Plugins" : "Pools"}
                </Button>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                className="gap-2"
                id="v2-plugin-install-open"
                onClick={() => setInstallModal({ ...EMPTY_INSTALL, open: true })}
                variant="outline"
              >
                <Plus aria-hidden="true" className="h-4 w-4" />
                Install plugin
              </Button>
              <Button
                className="gap-2"
                disabled={isRefreshing}
                onClick={() => void loadPlugins("manual")}
                variant="outline"
              >
                <RefreshCw aria-hidden="true" className={cn("h-4 w-4", isRefreshing ? "animate-spin" : "")} />
                {isRefreshing ? "Refreshing" : "Refresh"}
              </Button>
            </div>
          </div>
        </CardHeader>
      </Card>

      {actionNotice ? (
        <Card
          aria-live={actionNotice.tone === "error" ? "assertive" : "polite"}
          className={getNoticeToneClass(actionNotice.tone)}
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

      {error && !plugins.length ? (
        <Card className="border-rose-500/40">
          <CardContent className="flex flex-col items-start gap-3 p-4 sm:p-6">
            <div className="flex items-center gap-2 text-rose-300">
              <TriangleAlert aria-hidden="true" className="h-4 w-4" />
              <p className="text-sm font-medium">Unable to load plugins</p>
            </div>
            <p className="text-sm text-muted-foreground">{error}</p>
            <Button onClick={() => void loadPlugins("manual")} variant="outline">
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {isLoading ? (
        <Card aria-live="polite" role="status">
          <CardContent className="flex min-h-[14rem] items-center justify-center gap-2 p-6 text-sm text-muted-foreground">
            <Activity aria-hidden="true" className="h-4 w-4 animate-pulse text-primary" />
            Loading plugins...
          </CardContent>
        </Card>
      ) : null}

      {!isLoading && !error && !visiblePlugins.length ? (
        <Card>
          <CardContent className="flex min-h-[10rem] items-center justify-center p-6 text-sm text-muted-foreground">
            {tab === "pools" ? "No pool plugins found." : "No storage plugins found."}
          </CardContent>
        </Card>
      ) : null}

      {!isLoading && visiblePlugins.length ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {visiblePlugins.map((plugin) => (
            <PluginCard
              confirmingRemove={confirmRemoveId === plugin.id}
              key={plugin.id}
              onDetails={onDetails}
              onRemoveCancel={() => setConfirmRemoveId(null)}
              onRemoveConfirm={onRemoveConfirm}
              onRemoveRequest={(id) => setConfirmRemoveId(id)}
              onToggle={onToggle}
              pending={pendingId === plugin.id}
              plugin={plugin}
            />
          ))}
        </div>
      ) : null}

      {detailModal.open ? (
        <ModalOverlay onClose={closeDetails}>
          <Card
            aria-labelledby="v2-plugin-detail-title"
            aria-modal="true"
            className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden"
            id="v2-plugin-detail-modal"
            role="dialog"
          >
            <CardHeader className="flex flex-row items-start justify-between gap-3 border-b border-border/70 p-4 sm:p-5">
              <div className="space-y-1">
                <CardTitle className="text-base sm:text-lg" id="v2-plugin-detail-title">
                  {detailModal.name}
                </CardTitle>
                <CardDescription>Plugin status, recovery, logs, and commands.</CardDescription>
              </div>
              <Button id="v2-plugin-detail-close" onClick={closeDetails} variant="outline">
                Close
              </Button>
            </CardHeader>
            <CardContent className="space-y-4 overflow-auto p-4" id="v2-plugin-detail-content">
              {detailModal.status === "loading" ? (
                <p className="text-sm text-muted-foreground">Loading plugin details...</p>
              ) : detailModal.status === "error" ? (
                <p className="text-sm text-rose-300">{detailModal.error || "Failed to load plugin details"}</p>
              ) : detailModal.detail ? (
                <>
                  <div className="rounded-lg border border-border/70 bg-muted/25 p-3">
                    <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">Status</p>
                    <p className="text-sm">
                      {String(detailModal.detail.status?.message ?? detailModal.detail.status?.status ?? "—")}
                    </p>
                  </div>

                  {detailModal.detail.commands.length ? (
                    <div className="space-y-2">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Commands</p>
                      <div className="flex flex-wrap gap-2">
                        {detailModal.detail.commands.map((command) => {
                          // Commands with required params need the schema-driven config form
                          // (PH3-006b); disable rather than run them with empty params.
                          const needsParams = command.params.length > 0;
                          return (
                            <Button
                              className="gap-1.5 text-xs sm:text-sm"
                              data-plugin-command={command.id}
                              disabled={detailModal.command.running || needsParams}
                              key={command.id}
                              onClick={() => void runCommand(detailModal.detail!.id, command)}
                              size="sm"
                              title={
                                needsParams
                                  ? "Requires parameters — available in the upcoming plugin config editor"
                                  : undefined
                              }
                              variant="outline"
                            >
                              <Terminal aria-hidden="true" className="h-3.5 w-3.5" />
                              {command.label}
                              {needsParams ? " (needs params)" : ""}
                            </Button>
                          );
                        })}
                      </div>
                    </div>
                  ) : null}

                  {detailModal.command.commandId ? (
                    <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
                      <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
                        Command output {detailModal.command.running ? "(running...)" : ""}
                      </p>
                      <pre
                        className="max-h-[20vh] overflow-auto whitespace-pre-wrap break-words text-xs sm:text-sm"
                        id="v2-plugin-command-output"
                      >
                        {detailModal.command.error
                          ? detailModal.command.error
                          : detailModal.command.lines.join("\n") || "Waiting for output..."}
                      </pre>
                    </div>
                  ) : null}

                  {detailModal.recovery?.supported ? (
                    <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
                      <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">Recovery</p>
                      <pre className="max-h-[20vh] overflow-auto whitespace-pre-wrap break-words text-xs sm:text-sm">
                        {JSON.stringify(detailModal.recovery.data, null, 2)}
                      </pre>
                    </div>
                  ) : null}

                  {detailModal.log ? (
                    <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
                      <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">Latest log</p>
                      <pre className="max-h-[20vh] overflow-auto whitespace-pre-wrap break-words text-xs sm:text-sm">
                        {detailModal.log}
                      </pre>
                    </div>
                  ) : null}

                  <div className="space-y-2" id="v2-plugin-config">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Configuration (JSON)</p>
                    <textarea
                      aria-label="Plugin configuration JSON"
                      className="h-[24vh] w-full resize-y rounded-lg border border-border/70 bg-muted/25 p-3 font-mono text-xs sm:text-sm"
                      id="v2-plugin-config-textarea"
                      onChange={(event) =>
                        setDetailModal((current) => ({
                          ...current,
                          config: { ...current.config, text: event.target.value, status: "idle", error: null, details: [] },
                        }))
                      }
                      spellCheck={false}
                      value={detailModal.config.text}
                    />
                    {detailModal.config.error ? (
                      <p className="text-sm text-rose-300" id="v2-plugin-config-error">
                        {detailModal.config.error}
                        {detailModal.config.details.length ? `: ${detailModal.config.details.join("; ")}` : ""}
                      </p>
                    ) : null}
                    <div className="flex items-center gap-3">
                      <Button
                        disabled={detailModal.config.status === "saving"}
                        id="v2-plugin-config-save"
                        onClick={() => void saveConfig(detailModal.detail!.id, detailModal.config.text)}
                      >
                        {detailModal.config.status === "saving" ? "Saving..." : "Save config"}
                      </Button>
                      <span
                        aria-live="polite"
                        className="text-sm text-emerald-300"
                        id="v2-plugin-config-status"
                        role="status"
                      >
                        {detailModal.config.status === "saved" ? "Saved" : ""}
                      </span>
                    </div>
                    {Object.keys((detailModal.detail.schema?.properties as Record<string, unknown>) ?? {}).length ? (
                      <details className="text-xs text-muted-foreground">
                        <summary className="cursor-pointer">Schema fields</summary>
                        <ul className="mt-1 space-y-0.5">
                          {Object.entries((detailModal.detail.schema.properties as Record<string, Record<string, unknown>>)).map(
                            ([key, def]) => (
                              <li className="font-mono" key={key}>
                                {key}
                                {def?.type ? `: ${String(def.type)}` : ""}
                                {def?.description ? ` — ${String(def.description)}` : ""}
                              </li>
                            ),
                          )}
                        </ul>
                      </details>
                    ) : null}
                  </div>
                </>
              ) : null}
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}

      {installModal.open ? (
        <ModalOverlay onClose={() => setInstallModal(EMPTY_INSTALL)}>
          <Card
            aria-labelledby="v2-plugin-install-title"
            aria-modal="true"
            className="flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden"
            id="v2-plugin-install-modal"
            role="dialog"
          >
            <CardHeader className="flex flex-row items-start justify-between gap-3 border-b border-border/70 p-4 sm:p-5">
              <div className="space-y-1">
                <CardTitle className="text-base sm:text-lg" id="v2-plugin-install-title">
                  Install plugin
                </CardTitle>
                <CardDescription>Install a storage plugin from GitHub or pip.</CardDescription>
              </div>
              <Button id="v2-plugin-install-close" onClick={() => setInstallModal(EMPTY_INSTALL)} variant="outline">
                Close
              </Button>
            </CardHeader>
            <CardContent className="space-y-3 overflow-auto p-4">
              <label className="block space-y-1">
                <span className="text-xs uppercase tracking-wide text-muted-foreground">Type</span>
                <select
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                  data-install-field="type"
                  onChange={(event) => setInstallModal((current) => ({ ...current, type: event.target.value }))}
                  value={installModal.type}
                >
                  <option value="github">github</option>
                  <option value="pip">pip</option>
                </select>
              </label>
              {(
                [
                  ["source", "Source (repo URL or package)"],
                  ["id", "Plugin id (optional)"],
                  ["entry", "Entry module (optional)"],
                  ["class_name", "Class name (optional)"],
                ] as Array<[keyof InstallModalState, string]>
              ).map(([field, label]) => (
                <label className="block space-y-1" key={field}>
                  <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
                  <input
                    className="w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-xs sm:text-sm"
                    data-install-field={field}
                    onChange={(event) =>
                      setInstallModal((current) => ({ ...current, [field]: event.target.value }))
                    }
                    spellCheck={false}
                    value={String(installModal[field])}
                  />
                </label>
              ))}
              {installModal.error ? (
                <p className="text-sm text-rose-300" id="v2-plugin-install-error">
                  {installModal.error}
                </p>
              ) : null}
              <Button
                disabled={installModal.status === "saving" || !installModal.source.trim()}
                id="v2-plugin-install-submit"
                onClick={() => void installNewPlugin()}
              >
                {installModal.status === "saving" ? "Installing..." : "Install"}
              </Button>
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}
    </section>
  );
}
