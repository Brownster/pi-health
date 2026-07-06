import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Activity,
  Loader2,
  Plus,
  RefreshCw,
  TriangleAlert,
} from "lucide-react";

import { Badge, StatusBadge } from "@/components/ui/badge";
import { PluginCard } from "@/components/storage/plugin-card";
import { SnapraidCard } from "@/components/storage/snapraid-card";
import {
  MergerfsPoolCard,
  MergerfsSetupCard,
} from "@/components/storage/mergerfs-pool-card";
import { CommandRunner } from "@/components/storage/command-runner";
import { SnapraidEditor } from "@/components/storage/snapraid-editor";
import { mergerfsPools } from "@/lib/pools";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import { PageHeader } from "@/components/ui/page-header";
import {
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

const EMPTY_CONFIG: ConfigEditor = {
  text: "",
  status: "idle",
  error: null,
  details: [],
};
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

const EMPTY_COMMAND: CommandConsole = {
  running: false,
  commandId: null,
  lines: [],
  error: null,
};

function getNoticeToneClass(tone: ActionNotice["tone"]): string {
  if (tone === "success") return "border-success/30 text-success";
  if (tone === "error") return "border-danger/30 text-danger";
  return "border-info/30 text-info";
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "Unable to complete the request";
}

export function StoragePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [plugins, setPlugins] = useState<StoragePlugin[]>([]);
  const [tab, setTab] = useState<StorageTab>(
    location.pathname.includes("/pools") ? "pools" : "plugins",
  );
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState("Never");
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [confirmRemoveId, setConfirmRemoveId] = useState<string | null>(null);
  const [poolDetails, setPoolDetails] = useState<Record<string, PluginDetail | null>>({});
  const [configView, setConfigView] = useState<"guided" | "advanced">("guided");
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
  const [installModal, setInstallModal] =
    useState<InstallModalState>(EMPTY_INSTALL);
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

      // Pool cards need per-plugin status detail (list + per-plugin detail only).
      const poolPlugins = next.filter((plugin) => isPoolPlugin(plugin));
      void Promise.all(
        poolPlugins.map((plugin) =>
          fetchPluginDetail(plugin.id)
            .then((detail) => [plugin.id, detail] as const)
            .catch(() => [plugin.id, null] as const),
        ),
      ).then((entries) => {
        if (isMountedRef.current) {
          setPoolDetails(Object.fromEntries(entries));
        }
      });
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
          setActionNotice({
            tone: "error",
            message: getErrorMessage(caughtError),
          });
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
          setActionNotice({
            tone: "success",
            message: `Removed ${plugin.name}`,
          });
          await loadPlugins("manual");
        }
      } catch (caughtError) {
        if (isMountedRef.current) {
          setActionNotice({
            tone: "error",
            message: getErrorMessage(caughtError),
          });
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
    setConfigView("guided");
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
        fetchPluginRecovery(plugin.id).catch(
          () => ({ supported: false, data: null }) as PluginRecovery,
        ),
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
              config: {
                ...EMPTY_CONFIG,
                text: JSON.stringify(detail.config ?? {}, null, 2),
              },
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

  const saveConfig = useCallback(async (pluginId: string, text: string) => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(text) as Record<string, unknown>;
    } catch {
      setDetailModal((current) => ({
        ...current,
        config: {
          ...current.config,
          status: "error",
          error: "Config is not valid JSON",
          details: [],
        },
      }));
      return;
    }

    setDetailModal((current) => ({
      ...current,
      config: { ...current.config, status: "saving", error: null, details: [] },
    }));
    const result = await savePluginConfig(pluginId, parsed);
    if (!isMountedRef.current) {
      return;
    }
    if (result.ok) {
      setDetailModal((current) => ({
        ...current,
        config: {
          ...current.config,
          status: "saved",
          error: null,
          details: [],
        },
      }));
      setActionNotice({ tone: "success", message: "Plugin config saved" });
    } else {
      setDetailModal((current) => ({
        ...current,
        config: {
          ...current.config,
          status: "error",
          error: result.error,
          details: result.details,
        },
      }));
    }
  }, []);

  const installNewPlugin = useCallback(async () => {
    setInstallModal((current) => ({
      ...current,
      status: "saving",
      error: null,
    }));
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
        setInstallModal((current) => ({
          ...current,
          status: "error",
          error: getErrorMessage(caughtError),
        }));
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

  const visiblePlugins =
    tab === "pools"
      ? plugins.filter((plugin) => isPoolPlugin(plugin))
      : plugins;

  // Set up leads to the config editor. Until the guided editors land (PH4-004/005)
  // it opens the plugin detail modal, which already has config editing.
  const onSetup = onDetails;

  const renderPoolCards = (plugin: StoragePlugin) => {
    const detail = poolDetails[plugin.id] ?? null;
    const loading = !(plugin.id in poolDetails);

    if (plugin.id === "mergerfs") {
      const pools = mergerfsPools(detail);
      if (pools.length) {
        return pools.map((pool) => (
          <MergerfsPoolCard
            key={`${plugin.id}:${pool.name}`}
            onDetails={onDetails}
            plugin={plugin}
            pool={pool}
          />
        ));
      }
      return [
        <MergerfsSetupCard
          key={plugin.id}
          onDetails={onDetails}
          onSetup={onSetup}
          plugin={plugin}
        />,
      ];
    }

    if (plugin.id === "snapraid") {
      return [
        <SnapraidCard
          detail={detail}
          key={plugin.id}
          loading={loading}
          onDetails={onDetails}
          onSetup={onSetup}
          plugin={plugin}
        />,
      ];
    }

    return [
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
      />,
    ];
  };

  return (
    <section className="space-y-4 sm:space-y-6">
      <PageHeader
        actions={
          <>
            <Button
              className="gap-2"
              id="v2-plugin-install-open"
              onClick={() => setInstallModal({ ...EMPTY_INSTALL, open: true })}
              variant="secondary"
            >
              <Plus aria-hidden="true" className="h-4 w-4" />
              install plugin
            </Button>
            <Button
              className="gap-2"
              disabled={isRefreshing}
              onClick={() => void loadPlugins("manual")}
              variant="secondary"
            >
              <RefreshCw
                aria-hidden="true"
                className={cn("h-4 w-4", isRefreshing ? "animate-spin" : "")}
              />
              {isRefreshing ? "refreshing" : "refresh"}
            </Button>
          </>
        }
        description={`${visiblePlugins.length} ${tab} · synced ${lastUpdated}`}
        status={
          <StatusBadge
            label={`${visiblePlugins.filter((plugin) => plugin.enabled).length} enabled`}
            tone="success"
          />
        }
        title={tab === "pools" ? "storage_pools" : "storage_plugins"}
      />

      <div
        aria-label="Storage tabs"
        className="flex flex-wrap items-center gap-2"
        role="group"
      >
        {(["plugins", "pools"] as StorageTab[]).map((item) => (
          <Button
            aria-pressed={tab === item}
            data-storage-tab={item}
            key={item}
            onClick={() => navigate(item === "pools" ? "/pools" : "/plugins")}
            size="sm"
            variant={tab === item ? "default" : "outline"}
          >
            {item === "plugins" ? "Plugins" : "Pools"}
          </Button>
        ))}
      </div>

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
        <Card className="border-danger/30">
          <CardContent className="flex flex-col items-start gap-3 p-4 sm:p-6">
            <div className="flex items-center gap-2 text-danger">
              <TriangleAlert aria-hidden="true" className="h-4 w-4" />
              <p className="text-sm font-medium">Unable to load plugins</p>
            </div>
            <p className="text-sm text-muted-foreground">{error}</p>
            <Button
              onClick={() => void loadPlugins("manual")}
              variant="outline"
            >
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {isLoading ? (
        <Card aria-live="polite" role="status">
          <CardContent className="flex min-h-[14rem] items-center justify-center gap-2 p-6 text-sm text-muted-foreground">
            <Activity
              aria-hidden="true"
              className="h-4 w-4 animate-pulse text-primary"
            />
            Loading plugins...
          </CardContent>
        </Card>
      ) : null}

      {!isLoading && !error && !visiblePlugins.length ? (
        <Card>
          <CardContent className="flex min-h-[10rem] items-center justify-center p-6 text-sm text-muted-foreground">
            {tab === "pools"
              ? "No pool plugins found."
              : "No storage plugins found."}
          </CardContent>
        </Card>
      ) : null}

      {!isLoading && visiblePlugins.length ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {tab === "pools"
            ? visiblePlugins.flatMap((plugin) => renderPoolCards(plugin))
            : visiblePlugins.map((plugin) => (
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
                <CardTitle
                  className="text-base sm:text-lg"
                  id="v2-plugin-detail-title"
                >
                  {detailModal.name}
                </CardTitle>
                <CardDescription>
                  Plugin status, recovery, logs, and commands.
                </CardDescription>
              </div>
              <Button
                id="v2-plugin-detail-close"
                onClick={closeDetails}
                variant="outline"
              >
                Close
              </Button>
            </CardHeader>
            <CardContent
              className="space-y-4 overflow-auto p-4"
              id="v2-plugin-detail-content"
            >
              {detailModal.status === "loading" ? (
                <p className="text-sm text-muted-foreground">
                  Loading plugin details...
                </p>
              ) : detailModal.status === "error" ? (
                <p className="text-sm text-danger">
                  {detailModal.error || "Failed to load plugin details"}
                </p>
              ) : detailModal.detail ? (
                <>
                  <div className="rounded-lg border border-border/70 bg-muted/25 p-3">
                    <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">
                      Status
                    </p>
                    <p className="text-sm">
                      {String(
                        detailModal.detail.status?.message ??
                          detailModal.detail.status?.status ??
                          "—",
                      )}
                    </p>
                  </div>

                  {detailModal.detail.commands.length ? (
                    <CommandRunner
                      commands={detailModal.detail.commands}
                      onCompleted={() => void loadPlugins("manual")}
                      pluginId={detailModal.detail.id}
                      poolNames={mergerfsPools(detailModal.detail).map((pool) => pool.name)}
                    />
                  ) : null}

                  {detailModal.recovery?.supported ? (
                    <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
                      <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
                        Recovery
                      </p>
                      <pre className="max-h-[20vh] overflow-auto whitespace-pre-wrap break-words text-xs sm:text-sm">
                        {JSON.stringify(detailModal.recovery.data, null, 2)}
                      </pre>
                    </div>
                  ) : null}

                  {detailModal.log ? (
                    <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
                      <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
                        Latest log
                      </p>
                      <pre className="max-h-[20vh] overflow-auto whitespace-pre-wrap break-words text-xs sm:text-sm">
                        {detailModal.log}
                      </pre>
                    </div>
                  ) : null}

                  <div className="space-y-2" id="v2-plugin-config">
                    {detailModal.detail.id === "snapraid" ? (
                      <div className="flex flex-wrap gap-2">
                        <Button
                          data-config-view="guided"
                          onClick={() => setConfigView("guided")}
                          size="sm"
                          variant={configView === "guided" ? "default" : "outline"}
                        >
                          Guided
                        </Button>
                        <Button
                          data-config-view="advanced"
                          onClick={() => setConfigView("advanced")}
                          size="sm"
                          variant={configView === "advanced" ? "default" : "outline"}
                        >
                          Advanced (JSON)
                        </Button>
                      </div>
                    ) : null}

                    {detailModal.detail.id === "snapraid" && configView === "guided" ? (
                      <SnapraidEditor
                        config={detailModal.detail.config}
                        onSaved={() => void loadPlugins("manual")}
                        pluginId="snapraid"
                      />
                    ) : (
                    <>
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">
                      Configuration (JSON)
                    </p>
                    <textarea
                      aria-label="Plugin configuration JSON"
                      className="h-[24vh] w-full resize-y rounded-md border border-border bg-background p-3 font-mono text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm"
                      id="v2-plugin-config-textarea"
                      onChange={(event) =>
                        setDetailModal((current) => ({
                          ...current,
                          config: {
                            ...current.config,
                            text: event.target.value,
                            status: "idle",
                            error: null,
                            details: [],
                          },
                        }))
                      }
                      spellCheck={false}
                      value={detailModal.config.text}
                    />
                    {detailModal.config.error ? (
                      <p
                        className="text-sm text-danger"
                        id="v2-plugin-config-error"
                      >
                        {detailModal.config.error}
                        {detailModal.config.details.length
                          ? `: ${detailModal.config.details.join("; ")}`
                          : ""}
                      </p>
                    ) : null}
                    <div className="flex items-center gap-3">
                      <Button
                        disabled={detailModal.config.status === "saving"}
                        id="v2-plugin-config-save"
                        onClick={() =>
                          void saveConfig(
                            detailModal.detail!.id,
                            detailModal.config.text,
                          )
                        }
                      >
                        {detailModal.config.status === "saving"
                          ? "Saving..."
                          : "Save config"}
                      </Button>
                      <span
                        aria-live="polite"
                        className="text-sm text-success"
                        id="v2-plugin-config-status"
                        role="status"
                      >
                        {detailModal.config.status === "saved" ? "Saved" : ""}
                      </span>
                    </div>
                    {Object.keys(
                      (detailModal.detail.schema?.properties as Record<
                        string,
                        unknown
                      >) ?? {},
                    ).length ? (
                      <details className="text-xs text-muted-foreground">
                        <summary className="cursor-pointer">
                          Schema fields
                        </summary>
                        <ul className="mt-1 space-y-0.5">
                          {Object.entries(
                            detailModal.detail.schema.properties as Record<
                              string,
                              Record<string, unknown>
                            >,
                          ).map(([key, def]) => (
                            <li className="font-mono" key={key}>
                              {key}
                              {def?.type ? `: ${String(def.type)}` : ""}
                              {def?.description
                                ? ` — ${String(def.description)}`
                                : ""}
                            </li>
                          ))}
                        </ul>
                      </details>
                    ) : null}
                    </>
                    )}
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
                <CardTitle
                  className="text-base sm:text-lg"
                  id="v2-plugin-install-title"
                >
                  Install plugin
                </CardTitle>
                <CardDescription>
                  Install a storage plugin from GitHub or pip.
                </CardDescription>
              </div>
              <Button
                id="v2-plugin-install-close"
                onClick={() => setInstallModal(EMPTY_INSTALL)}
                variant="outline"
              >
                Close
              </Button>
            </CardHeader>
            <CardContent className="space-y-3 overflow-auto p-4">
              <label className="block space-y-1">
                <span className="text-xs uppercase tracking-wide text-muted-foreground">
                  Type
                </span>
                <select
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                  data-install-field="type"
                  onChange={(event) =>
                    setInstallModal((current) => ({
                      ...current,
                      type: event.target.value,
                    }))
                  }
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
                  <span className="text-xs uppercase tracking-wide text-muted-foreground">
                    {label}
                  </span>
                  <input
                    className="w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-xs sm:text-sm"
                    data-install-field={field}
                    onChange={(event) =>
                      setInstallModal((current) => ({
                        ...current,
                        [field]: event.target.value,
                      }))
                    }
                    spellCheck={false}
                    value={String(installModal[field])}
                  />
                </label>
              ))}
              {installModal.error ? (
                <p className="text-sm text-danger" id="v2-plugin-install-error">
                  {installModal.error}
                </p>
              ) : null}
              <Button
                disabled={
                  installModal.status === "saving" ||
                  !installModal.source.trim()
                }
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
