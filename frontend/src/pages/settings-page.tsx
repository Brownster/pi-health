import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, RefreshCw, Settings as SettingsIcon, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
  restoreBackup,
  runAutoUpdateNow,
  runBackup,
  saveAutoUpdateConfig,
  saveBackupConfig,
  savePiHealthUpdateConfig,
  triggerPiHealthUpdate,
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
          "w-full rounded-md border border-border bg-background px-3 py-2 text-xs sm:text-sm",
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
        className="h-4 w-4"
        data-setting={testId}
        onChange={(event) => onChange(event.target.checked)}
        type="checkbox"
      />
      {label}
    </label>
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
      <Card>
        <CardHeader className="space-y-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0 space-y-1">
              <CardTitle className="flex items-center gap-2 text-lg sm:text-xl">
                <SettingsIcon aria-hidden="true" className="h-5 w-5 text-primary" />
                Settings
              </CardTitle>
              <CardDescription>Self-update, backups, and container auto-update.</CardDescription>
            </div>
            <span className="inline-flex min-h-11 items-center rounded-md border border-border bg-muted/70 px-3 text-xs text-muted-foreground">
              Last updated: {lastUpdated}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button className="gap-2" disabled={isRefreshing} onClick={() => void loadAll("manual")} variant="outline">
              <RefreshCw aria-hidden="true" className={cn("h-4 w-4", isRefreshing ? "animate-spin" : "")} />
              {isRefreshing ? "Refreshing" : "Refresh"}
            </Button>
          </div>
        </CardHeader>
      </Card>

      {actionNotice ? (
        <Card
          aria-live={actionNotice.tone === "error" ? "assertive" : "polite"}
          className={actionNotice.tone === "error" ? "border-rose-500/40 text-rose-300" : "border-emerald-500/40 text-emerald-300"}
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
        <Card aria-live="polite" className="border-amber-500/40" role="status">
          <CardContent className="flex items-center gap-2 p-4 text-sm text-amber-300">
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
        <>
          {/* Pi-Health self-update */}
          <Card id="v2-settings-pihealth">
            <CardHeader>
              <CardTitle className="text-base sm:text-lg">Pi-Health self-update</CardTitle>
              <CardDescription>Update Pi-Health from its git repository and restart the service.</CardDescription>
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
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  disabled={busy}
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
                      className="border-violet-500/40 text-violet-300 hover:bg-violet-500/15"
                      id="v2-settings-pihealth-update-confirm"
                      onClick={() =>
                        void runAction("update-pihealth", async () => {
                          await triggerPiHealthUpdate();
                        }, "Pi-Health update triggered")
                      }
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
                    disabled={busy}
                    id="v2-settings-pihealth-update"
                    onClick={() => setConfirmKey("update-pihealth")}
                    variant="outline"
                  >
                    Update now
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Backups */}
          <Card id="v2-settings-backups">
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
                        className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/70 bg-muted/20 p-2 text-xs"
                        key={archive}
                      >
                        <span className="break-all font-mono">{archive}</span>
                        {confirmKey === restoreKey ? (
                          <span className="flex items-center gap-1.5">
                            <Button
                              className="border-amber-500/40 text-amber-300 hover:bg-amber-500/15 text-xs sm:text-sm"
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
          <Card id="v2-settings-auto-update">
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
        </>
      )}
    </section>
  );
}
