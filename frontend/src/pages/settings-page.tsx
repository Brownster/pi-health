import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, ArrowRight, CheckCircle2, Loader2, PackageOpen, RefreshCw, TriangleAlert } from "lucide-react";
import { Link } from "react-router-dom";

import { StatusBadge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import {
  type AutoUpdateConfig,
  type BackupConfig,
  type BackupStatus,
  type PiHealthUpdateConfig,
  fetchAutoUpdateConfig,
  fetchBackupConfig,
  fetchBackupList,
  fetchBackupStatus,
  fetchPiHealthUpdateConfig,
  isStillAuthenticated,
  type OperationEvent,
  restoreBackup,
  runAutoUpdateNow,
  runBackup,
  runPiHealthUpdate,
  saveAutoUpdateConfig,
  saveBackupConfig,
  savePiHealthUpdateConfig,
  waitForServiceRecovery,
} from "@/lib/settings";
import { formatClockTime } from "@/lib/format";
import { cn } from "@/lib/utils";

interface ActionNotice {
  message: string;
  tone: "success" | "error";
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "Unable to complete the request";
}

function TextField({
  label,
  value,
  onChange,
  mono = true,
  testId,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  mono?: boolean;
  testId: string;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
      <input
        className={cn(
          "w-full rounded-md border border-border bg-background px-3 py-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm",
          mono ? "font-mono" : "",
        )}
        data-setting={testId}
        onChange={(event) => onChange(event.target.value)}
        spellCheck={false}
        value={value}
      />
    </label>
  );
}

function ToggleField({
  label,
  checked,
  onChange,
  testId,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  testId: string;
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input
        checked={checked}
        className="h-4 w-4 accent-primary"
        data-setting={testId}
        onChange={(event) => onChange(event.target.checked)}
        type="checkbox"
      />
      {label}
    </label>
  );
}

type UpdatePhase = "idle" | "running" | "restarting" | "recovered" | "loggedout" | "failed";

interface UpdateLogLine {
  step?: string;
  text: string;
  tone: "info" | "error";
}

function UpdateProgressPanel({
  phase,
  log,
  commit,
}: {
  phase: UpdatePhase;
  log: UpdateLogLine[];
  commit: string | null;
}) {
  const header = (() => {
    switch (phase) {
      case "running":
        return { icon: <Loader2 aria-hidden className="h-4 w-4 animate-spin" />, text: "Updating…", tone: "info" as const };
      case "restarting":
        return { icon: <Loader2 aria-hidden className="h-4 w-4 animate-spin" />, text: "Restarting — reconnecting…", tone: "info" as const };
      case "recovered":
        return {
          icon: <CheckCircle2 aria-hidden className="h-4 w-4" />,
          text: commit ? `Update complete — now at ${commit}.` : "Update complete.",
          tone: "success" as const,
        };
      case "loggedout":
        return {
          icon: <CheckCircle2 aria-hidden className="h-4 w-4" />,
          text: commit ? `Update complete (now at ${commit}) — please log in again.` : "Update complete — please log in again.",
          tone: "success" as const,
        };
      case "failed":
        return { icon: <TriangleAlert aria-hidden className="h-4 w-4" />, text: "Update failed.", tone: "error" as const };
      default:
        return null;
    }
  })();

  if (!header) {
    return null;
  }

  return (
    <div className="mt-3 space-y-2 rounded-md border border-border bg-muted/30 p-3" data-testid="pihealth-update-progress">
      <div
        className={cn(
          "flex items-center gap-2 text-sm font-medium",
          header.tone === "success" ? "text-success" : header.tone === "error" ? "text-danger" : "text-info",
        )}
      >
        {header.icon}
        <span>{header.text}</span>
      </div>
      {log.length > 0 ? (
        <ul className="max-h-48 space-y-1 overflow-y-auto font-mono text-xs">
          {log.map((line, index) => (
            <li
              key={index}
              className={cn("flex gap-2", line.tone === "error" ? "text-danger" : "text-muted-foreground")}
            >
              {line.step ? <span className="shrink-0 uppercase tracking-wide opacity-70">{line.step}</span> : null}
              <span className="break-all">{line.text}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {phase === "loggedout" ? (
        <Button onClick={() => window.location.assign("/login.html")} variant="outline">
          Go to login
        </Button>
      ) : null}
    </div>
  );
}

export function SettingsPage() {
  const [pihealth, setPihealth] = useState<PiHealthUpdateConfig>({ repo_path: "", service_name: "" });
  const [backup, setBackup] = useState<BackupConfig>({
    enabled: false,
    schedule_preset: "daily",
    retention_count: null,
    dest_dir: "",
  });
  const [backupStatus, setBackupStatus] = useState<BackupStatus | null>(null);
  const [backups, setBackups] = useState<string[]>([]);
  const [autoUpdate, setAutoUpdate] = useState<AutoUpdateConfig>({
    enabled: false,
    schedule_preset: "daily_4am",
    notify_on_update: false,
  });
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState("Never");
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [confirmKey, setConfirmKey] = useState<string | null>(null);
  const [updatePhase, setUpdatePhase] = useState<UpdatePhase>("idle");
  const [updateLog, setUpdateLog] = useState<UpdateLogLine[]>([]);
  const [updateCommit, setUpdateCommit] = useState<string | null>(null);
  const isMountedRef = useRef(true);

  const loadAll = useCallback(async (reason: "initial" | "manual") => {
    if (reason === "initial") {
      setIsLoading(true);
    } else {
      setIsRefreshing(true);
    }
    try {
      const [ph, bkCfg, bkStatus, bkList, au] = await Promise.all([
        fetchPiHealthUpdateConfig(),
        fetchBackupConfig(),
        fetchBackupStatus().catch(() => null),
        fetchBackupList().catch(() => []),
        fetchAutoUpdateConfig(),
      ]);
      if (!isMountedRef.current) {
        return;
      }
      setPihealth(ph);
      setBackup(bkCfg);
      setBackupStatus(bkStatus);
      setBackups(bkList);
      setAutoUpdate(au);
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

  const runAction = useCallback(
    async (key: string, action: () => Promise<void>, successMessage: string, reload = false) => {
      if (pendingKey) {
        return;
      }
      setPendingKey(key);
      setConfirmKey(null);
      try {
        await action();
        if (isMountedRef.current) {
          setActionNotice({ tone: "success", message: successMessage });
          if (reload) {
            await loadAll("manual");
          }
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

  const runUpdate = useCallback(async () => {
    if (updatePhase === "running" || updatePhase === "restarting") {
      return;
    }
    setConfirmKey(null);
    setUpdatePhase("running");
    setUpdateLog([]);
    setUpdateCommit(null);

    let sawRestart = false;
    let sawError = false;

    const onEvent = (event: OperationEvent) => {
      if (!isMountedRef.current) {
        return;
      }
      if (event.new_commit) {
        setUpdateCommit(event.new_commit.slice(0, 8));
      }
      if (event.error) {
        sawError = true;
        setUpdateLog((lines) => [...lines, { step: event.step, text: event.error ?? "Update failed", tone: "error" }]);
        return;
      }
      if (event.line) {
        setUpdateLog((lines) => [...lines, { step: event.step, text: event.line ?? "", tone: "info" }]);
      }
      if (event.restarting) {
        sawRestart = true;
        setUpdatePhase("restarting");
      }
    };

    try {
      await runPiHealthUpdate(onEvent);
    } catch (caughtError) {
      if (!isMountedRef.current) {
        return;
      }
      sawError = true;
      setUpdateLog((lines) => [...lines, { text: getErrorMessage(caughtError), tone: "error" }]);
    }

    if (!isMountedRef.current) {
      return;
    }
    if (sawError) {
      setUpdatePhase("failed");
      return;
    }
    if (!sawRestart) {
      // "Already up to date" — the service was not restarted.
      setUpdatePhase("recovered");
      return;
    }

    const recovered = await waitForServiceRecovery();
    if (!isMountedRef.current) {
      return;
    }
    if (!recovered) {
      setUpdateLog((lines) => [...lines, { text: "Timed out waiting for the service to come back online.", tone: "error" }]);
      setUpdatePhase("failed");
      return;
    }
    const stillAuthenticated = await isStillAuthenticated();
    if (!isMountedRef.current) {
      return;
    }
    setUpdatePhase(stillAuthenticated ? "recovered" : "loggedout");
  }, [updatePhase]);

  useEffect(() => {
    isMountedRef.current = true;
    void loadAll("initial");
    return () => {
      isMountedRef.current = false;
    };
  }, [loadAll]);

  const busy = Boolean(pendingKey);

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
        description={`system configuration · synced ${lastUpdated}`}
        status={<StatusBadge label="config ready" tone="success" />}
        title="system_settings"
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
            Loading settings...
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 xl:grid-cols-3 xl:items-start">
          {/* Pi-Health self-update */}
          <Card className="transition-colors duration-200 hover:border-primary/25" id="v2-settings-pihealth">
            <CardHeader>
              <CardTitle className="text-base sm:text-lg">Pi-Health self-update</CardTitle>
              <CardDescription>
                Pull the latest code, install dependencies, apply migrations, refresh the UI, and restart — with live progress.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <TextField
                label="Repo path"
                onChange={(value) => setPihealth((c) => ({ ...c, repo_path: value }))}
                testId="pihealth-repo"
                value={pihealth.repo_path}
              />
              <TextField
                label="Service name"
                onChange={(value) => setPihealth((c) => ({ ...c, service_name: value }))}
                testId="pihealth-service"
                value={pihealth.service_name}
              />
              {(() => {
                const updateInFlight = updatePhase === "running" || updatePhase === "restarting";
                return (
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      disabled={busy || updateInFlight}
                      id="v2-settings-pihealth-save"
                      onClick={() =>
                        void runAction("save-pihealth", () => savePiHealthUpdateConfig(pihealth), "Pi-Health update config saved")
                      }
                    >
                      {pendingKey === "save-pihealth" ? "Saving..." : "Save"}
                    </Button>
                    {confirmKey === "update-pihealth" ? (
                      <span className="flex items-center gap-1.5">
                        <Button
                          className="border-info/30 bg-info/10 text-info hover:bg-info/15"
                          id="v2-settings-pihealth-update-confirm"
                          onClick={() => void runUpdate()}
                          variant="outline"
                        >
                          Confirm update
                        </Button>
                        <Button onClick={() => setConfirmKey(null)} variant="outline">
                          Cancel
                        </Button>
                      </span>
                    ) : (
                      <Button
                        disabled={busy || updateInFlight}
                        id="v2-settings-pihealth-update"
                        onClick={() => setConfirmKey("update-pihealth")}
                        variant="outline"
                      >
                        {updateInFlight ? "Updating…" : "Update now"}
                      </Button>
                    )}
                  </div>
                );
              })()}
              <UpdateProgressPanel commit={updateCommit} log={updateLog} phase={updatePhase} />
            </CardContent>
          </Card>

          {/* Backups */}
          <Card className="transition-colors duration-200 hover:border-primary/25" id="v2-settings-backups">
            <CardHeader>
              <CardTitle className="text-base sm:text-lg">Backups</CardTitle>
              <CardDescription>
                {backupStatus
                  ? `Next run: ${backupStatus.next_run || "—"} · Last: ${backupStatus.last_run || "never"}`
                  : "Scheduled configuration backups."}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <ToggleField
                checked={backup.enabled}
                label="Enabled"
                onChange={(checked) => setBackup((c) => ({ ...c, enabled: checked }))}
                testId="backup-enabled"
              />
              <TextField
                label="Schedule preset"
                mono={false}
                onChange={(value) => setBackup((c) => ({ ...c, schedule_preset: value }))}
                testId="backup-schedule"
                value={backup.schedule_preset}
              />
              <TextField
                label="Destination dir"
                onChange={(value) => setBackup((c) => ({ ...c, dest_dir: value }))}
                testId="backup-dest"
                value={backup.dest_dir}
              />
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  disabled={busy}
                  id="v2-settings-backup-save"
                  onClick={() =>
                    void runAction(
                      "save-backup",
                      () =>
                        saveBackupConfig({
                          enabled: backup.enabled,
                          schedule_preset: backup.schedule_preset,
                          dest_dir: backup.dest_dir,
                        }),
                      "Backup config saved",
                    )
                  }
                >
                  {pendingKey === "save-backup" ? "Saving..." : "Save"}
                </Button>
                <Button
                  disabled={busy}
                  id="v2-settings-backup-run"
                  onClick={() => void runAction("run-backup", () => runBackup(), "Backup started", true)}
                  variant="outline"
                >
                  Run backup now
                </Button>
              </div>

              {backups.length ? (
                <div className="space-y-2">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Backups</p>
                  {backups.map((archive) => {
                    const restoreKey = `restore:${archive}`;
                    return (
                      <div
                        className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-muted/20 p-2 text-xs"
                        key={archive}
                      >
                        <span className="break-all font-mono">{archive}</span>
                        {confirmKey === restoreKey ? (
                          <span className="flex items-center gap-1.5">
                            <Button
                              className="border-warning/30 bg-warning/10 text-warning hover:bg-warning/15 text-xs sm:text-sm"
                              data-confirm-restore={archive}
                              onClick={() =>
                                void runAction(restoreKey, () => restoreBackup(archive), `Restored ${archive}`, true)
                              }
                              size="sm"
                              variant="outline"
                            >
                              Confirm restore
                            </Button>
                            <Button onClick={() => setConfirmKey(null)} size="sm" variant="outline">
                              Cancel
                            </Button>
                          </span>
                        ) : (
                          <Button
                            className="text-xs sm:text-sm"
                            data-restore={archive}
                            disabled={busy}
                            onClick={() => setConfirmKey(restoreKey)}
                            size="sm"
                            variant="outline"
                          >
                            Restore
                          </Button>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </CardContent>
          </Card>

          {/* Auto-update */}
          <Card className="transition-colors duration-200 hover:border-primary/25" id="v2-settings-auto-update">
            <CardHeader>
              <CardTitle className="text-base sm:text-lg">Container auto-update</CardTitle>
              <CardDescription>Scheduled container image updates.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <ToggleField
                checked={autoUpdate.enabled}
                label="Enabled"
                onChange={(checked) => setAutoUpdate((c) => ({ ...c, enabled: checked }))}
                testId="autoupdate-enabled"
              />
              <ToggleField
                checked={autoUpdate.notify_on_update}
                label="Notify on update"
                onChange={(checked) => setAutoUpdate((c) => ({ ...c, notify_on_update: checked }))}
                testId="autoupdate-notify"
              />
              <TextField
                label="Schedule preset"
                mono={false}
                onChange={(value) => setAutoUpdate((c) => ({ ...c, schedule_preset: value }))}
                testId="autoupdate-schedule"
                value={autoUpdate.schedule_preset}
              />
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  disabled={busy}
                  id="v2-settings-auto-update-save"
                  onClick={() =>
                    void runAction("save-autoupdate", () => saveAutoUpdateConfig(autoUpdate), "Auto-update config saved")
                  }
                >
                  {pendingKey === "save-autoupdate" ? "Saving..." : "Save"}
                </Button>
                <Button
                  disabled={busy}
                  id="v2-settings-auto-update-run"
                  onClick={() => void runAction("run-autoupdate", () => runAutoUpdateNow(), "Auto-update run started")}
                  variant="outline"
                >
                  Run now
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card className="transition-colors duration-200 hover:border-primary/25 xl:col-span-3" id="v2-settings-advanced">
            <CardHeader>
              <CardTitle className="text-base sm:text-lg">Advanced</CardTitle>
              <CardDescription>Inspect installed capability extensions and provider diagnostics.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex min-w-0 items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-border bg-muted/30 text-primary">
                  <PackageOpen aria-hidden="true" className="h-5 w-5" />
                </span>
                <div className="min-w-0">
                  <p className="font-mono text-sm font-semibold">Extensions</p>
                  <p className="mt-1 text-xs text-muted-foreground">Versions, compatibility, capabilities, sources, and registry health.</p>
                </div>
              </div>
              <Link className={cn(buttonVariants({ variant: "outline" }), "shrink-0 gap-2")} to="/settings/extensions">
                Open extensions
                <ArrowRight aria-hidden="true" className="h-4 w-4" />
              </Link>
            </CardContent>
          </Card>
        </div>
      )}
    </section>
  );
}
