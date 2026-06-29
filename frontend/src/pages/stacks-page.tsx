import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Loader2, RefreshCw, TriangleAlert } from "lucide-react";

import { STACK_ACTION_META, StackCard } from "@/components/stacks/stack-card";
import { StatusBadge } from "@/components/ui/badge";
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
  type StackAction,
  type StackSummary,
  createStackOperation,
  fetchStackBackups,
  fetchStackCompose,
  fetchStackEnv,
  fetchStackLogs,
  fetchStacks,
  restoreStackBackup,
  saveStackCompose,
  saveStackEnv,
  streamStackOperation,
} from "@/lib/stacks";
import { formatClockTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 10_000;

type AsyncStatus = "idle" | "loading" | "ready" | "error";
type ConsoleStatus = "streaming" | "done" | "error";

interface ActionNotice {
  message: string;
  tone: "info" | "success" | "error";
}

interface ConsoleModalState {
  open: boolean;
  stackName: string;
  action: StackAction | null;
  status: ConsoleStatus;
  lines: string[];
  returncode: number | null;
  error: string | null;
}

interface LogsModalState {
  open: boolean;
  status: AsyncStatus;
  stackName: string;
  logs: string;
  error: string | null;
}

type EditorTab = "compose" | "env";
type SaveStatus = "idle" | "saving" | "saved" | "error";

interface EditorModalState {
  open: boolean;
  stackName: string;
  tab: EditorTab;
  status: AsyncStatus;
  loadError: string | null;
  compose: string;
  composeFilename: string | null;
  env: string;
  saveStatus: SaveStatus;
  saveError: string | null;
}

interface BackupsModalState {
  open: boolean;
  stackName: string;
  status: AsyncStatus;
  backups: string[];
  error: string | null;
  confirming: string | null;
  restoring: string | null;
  notice: string | null;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "Unable to complete the request";
}

function getNoticeToneClass(tone: ActionNotice["tone"]): string {
  if (tone === "success") {
    return "border-success/30 text-success";
  }
  if (tone === "error") {
    return "border-danger/30 text-danger";
  }
  return "border-info/30 text-info";
}

export function StacksPage() {
  const [stacks, setStacks] = useState<StackSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState("Never");
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [pendingActions, setPendingActions] = useState<
    Record<string, StackAction>
  >({});
  const [consoleModal, setConsoleModal] = useState<ConsoleModalState>({
    open: false,
    stackName: "",
    action: null,
    status: "streaming",
    lines: [],
    returncode: null,
    error: null,
  });
  const [logsModal, setLogsModal] = useState<LogsModalState>({
    open: false,
    status: "idle",
    stackName: "",
    logs: "",
    error: null,
  });
  const [editorModal, setEditorModal] = useState<EditorModalState>({
    open: false,
    stackName: "",
    tab: "compose",
    status: "idle",
    loadError: null,
    compose: "",
    composeFilename: null,
    env: "",
    saveStatus: "idle",
    saveError: null,
  });
  const [backupsModal, setBackupsModal] = useState<BackupsModalState>({
    open: false,
    stackName: "",
    status: "idle",
    backups: [],
    error: null,
    confirming: null,
    restoring: null,
    notice: null,
  });

  const isMountedRef = useRef(true);
  const stacksLoadInFlightRef = useRef(false);
  const pendingActionsRef = useRef<Record<string, StackAction>>({});
  const stackStreamAbortRef = useRef<{
    controller: AbortController;
    stackName: string;
  } | null>(null);

  const setPendingAction = useCallback(
    (name: string, action: StackAction | null) => {
      setPendingActions((current) => {
        const next = { ...current };
        if (action) {
          next[name] = action;
        } else {
          delete next[name];
        }
        pendingActionsRef.current = next;
        return next;
      });
    },
    [],
  );

  const loadStacks = useCallback(
    async (reason: "initial" | "manual" | "poll" | "action") => {
      if (stacksLoadInFlightRef.current) {
        return;
      }
      stacksLoadInFlightRef.current = true;

      if (reason === "initial") {
        setIsLoading(true);
      }
      if (reason === "manual") {
        setIsRefreshing(true);
      }

      try {
        const next = await fetchStacks({ includeStatus: true });
        if (!isMountedRef.current) {
          return;
        }
        setStacks(next);
        setError(null);
        setLastUpdated(formatClockTime(new Date()));
      } catch (caughtError) {
        if (!isMountedRef.current) {
          return;
        }
        setError(getErrorMessage(caughtError));
      } finally {
        stacksLoadInFlightRef.current = false;
        if (isMountedRef.current) {
          if (reason === "initial") {
            setIsLoading(false);
          }
          if (reason === "manual") {
            setIsRefreshing(false);
          }
        }
      }
    },
    [],
  );

  const closeStackStream = useCallback(() => {
    if (stackStreamAbortRef.current) {
      stackStreamAbortRef.current.controller.abort();
      stackStreamAbortRef.current = null;
    }
  }, []);

  const onAction = useCallback(
    (stack: StackSummary, action: StackAction) => {
      if (pendingActionsRef.current[stack.name]) {
        return;
      }

      const meta = STACK_ACTION_META[action];
      setPendingAction(stack.name, action);
      setActionNotice({
        tone: "info",
        message: `${meta.pendingLabel.replace("...", "")} ${stack.name}...`,
      });
      setConsoleModal({
        open: true,
        stackName: stack.name,
        action,
        status: "streaming",
        lines: [],
        returncode: null,
        error: null,
      });

      if (stackStreamAbortRef.current) {
        stackStreamAbortRef.current.controller.abort();
        setPendingAction(stackStreamAbortRef.current.stackName, null);
      }
      const controller = new AbortController();
      stackStreamAbortRef.current = { controller, stackName: stack.name };
      let terminalReceived = false;

      const execute = async () => {
        try {
          const operation = await createStackOperation(
            stack.name,
            action,
            controller.signal,
          );
          await streamStackOperation(
            operation.stream_url,
            (data) => {
              if (!isMountedRef.current || controller.signal.aborted) {
                return;
              }
              if (data.error) {
                terminalReceived = true;
                setConsoleModal((current) => ({
                  ...current,
                  status: "error",
                  error: data.error ?? "Stream error",
                }));
                setActionNotice({
                  tone: "error",
                  message: `${meta.label} failed for ${stack.name}`,
                });
                return;
              }
              if (data.done) {
                terminalReceived = true;
                const failed =
                  typeof data.returncode === "number" && data.returncode !== 0;
                setConsoleModal((current) => ({
                  ...current,
                  status: failed ? "error" : "done",
                  returncode: data.returncode ?? null,
                  error: failed
                    ? `Command exited with code ${data.returncode}`
                    : null,
                }));
                setActionNotice({
                  tone: failed ? "error" : "success",
                  message: failed
                    ? `${meta.label} failed for ${stack.name}`
                    : `${meta.label} completed for ${stack.name}`,
                });
                return;
              }
              if (typeof data.line === "string") {
                setConsoleModal((current) => ({
                  ...current,
                  lines: [...current.lines, data.line as string],
                }));
              }
            },
            controller.signal,
          );
          if (!terminalReceived) {
            throw new Error("Stack operation ended without a result");
          }
        } catch (caughtError) {
          if (controller.signal.aborted) {
            return;
          }
          if (!isMountedRef.current) {
            return;
          }
          setConsoleModal((current) => ({
            ...current,
            status: "error",
            error: getErrorMessage(caughtError),
          }));
          setActionNotice({
            tone: "error",
            message: `${meta.label} failed for ${stack.name}: ${getErrorMessage(caughtError)}`,
          });
        } finally {
          if (stackStreamAbortRef.current?.controller === controller) {
            stackStreamAbortRef.current = null;
          }
          if (!controller.signal.aborted && isMountedRef.current) {
            setPendingAction(stack.name, null);
            void loadStacks("action");
          }
        }
      };
      void execute();
    },
    [loadStacks, setPendingAction],
  );

  const closeConsole = useCallback(() => {
    setConsoleModal((current) => {
      if (current.status === "streaming") {
        // User dismissed mid-run: stop listening; the server operation continues once.
        closeStackStream();
        if (current.stackName) {
          setPendingAction(current.stackName, null);
        }
      }
      return { ...current, open: false };
    });
  }, [closeStackStream, setPendingAction]);

  const onLogs = useCallback(async (stack: StackSummary) => {
    setLogsModal({
      open: true,
      status: "loading",
      stackName: stack.name,
      logs: "",
      error: null,
    });
    try {
      const result = await fetchStackLogs(stack.name);
      if (!isMountedRef.current) {
        return;
      }
      setLogsModal({
        open: true,
        status: "ready",
        stackName: stack.name,
        logs: result.logs || "No logs available.",
        error: null,
      });
    } catch (caughtError) {
      if (!isMountedRef.current) {
        return;
      }
      setLogsModal({
        open: true,
        status: "error",
        stackName: stack.name,
        logs: "",
        error: getErrorMessage(caughtError),
      });
    }
  }, []);

  const closeLogs = useCallback(() => {
    setLogsModal((current) => ({ ...current, open: false }));
  }, []);

  const onEdit = useCallback(async (stack: StackSummary) => {
    setEditorModal({
      open: true,
      stackName: stack.name,
      tab: "compose",
      status: "loading",
      loadError: null,
      compose: "",
      composeFilename: null,
      env: "",
      saveStatus: "idle",
      saveError: null,
    });

    try {
      const [compose, env] = await Promise.all([
        fetchStackCompose(stack.name),
        fetchStackEnv(stack.name),
      ]);
      if (!isMountedRef.current) {
        return;
      }
      setEditorModal((current) =>
        current.stackName === stack.name && current.open
          ? {
              ...current,
              status: "ready",
              compose: compose.content,
              composeFilename: compose.filename,
              env: env.content,
            }
          : current,
      );
    } catch (caughtError) {
      if (!isMountedRef.current) {
        return;
      }
      setEditorModal((current) =>
        current.stackName === stack.name && current.open
          ? {
              ...current,
              status: "error",
              loadError: getErrorMessage(caughtError),
            }
          : current,
      );
    }
  }, []);

  const closeEditor = useCallback(() => {
    setEditorModal((current) => ({ ...current, open: false }));
  }, []);

  const saveEditor = useCallback(async () => {
    const name = editorModal.stackName;
    const tab = editorModal.tab;
    const content = tab === "compose" ? editorModal.compose : editorModal.env;
    setEditorModal((current) => ({
      ...current,
      saveStatus: "saving",
      saveError: null,
    }));

    try {
      if (tab === "compose") {
        await saveStackCompose(name, content);
      } else {
        await saveStackEnv(name, content);
      }
      if (!isMountedRef.current) {
        return;
      }
      setEditorModal((current) => ({
        ...current,
        saveStatus: "saved",
        saveError: null,
      }));
      setActionNotice({ tone: "success", message: `Saved ${tab} for ${name}` });
    } catch (caughtError) {
      if (!isMountedRef.current) {
        return;
      }
      setEditorModal((current) => ({
        ...current,
        saveStatus: "error",
        saveError: getErrorMessage(caughtError),
      }));
    }
  }, [editorModal]);

  const onBackups = useCallback(async (stack: StackSummary) => {
    setBackupsModal({
      open: true,
      stackName: stack.name,
      status: "loading",
      backups: [],
      error: null,
      confirming: null,
      restoring: null,
      notice: null,
    });

    try {
      const backups = await fetchStackBackups(stack.name);
      if (!isMountedRef.current) {
        return;
      }
      setBackupsModal((current) =>
        current.stackName === stack.name && current.open
          ? { ...current, status: "ready", backups }
          : current,
      );
    } catch (caughtError) {
      if (!isMountedRef.current) {
        return;
      }
      setBackupsModal((current) =>
        current.stackName === stack.name && current.open
          ? { ...current, status: "error", error: getErrorMessage(caughtError) }
          : current,
      );
    }
  }, []);

  const closeBackups = useCallback(() => {
    setBackupsModal((current) => ({ ...current, open: false }));
  }, []);

  const restoreBackup = useCallback(
    async (stackName: string, backup: string) => {
      setBackupsModal((current) => ({
        ...current,
        confirming: null,
        restoring: backup,
        notice: null,
      }));
      try {
        await restoreStackBackup(stackName, backup);
        if (!isMountedRef.current) {
          return;
        }
        setBackupsModal((current) => ({
          ...current,
          restoring: null,
          notice: `Restored ${backup}`,
        }));
        setActionNotice({
          tone: "success",
          message: `Restored ${stackName} from ${backup}`,
        });
        void loadStacks("action");
      } catch (caughtError) {
        if (!isMountedRef.current) {
          return;
        }
        setBackupsModal((current) => ({
          ...current,
          restoring: null,
          error: getErrorMessage(caughtError),
        }));
        setActionNotice({
          tone: "error",
          message: `Restore failed for ${stackName}: ${getErrorMessage(caughtError)}`,
        });
      }
    },
    [loadStacks],
  );

  useEffect(() => {
    isMountedRef.current = true;
    void loadStacks("initial");

    const intervalId = window.setInterval(() => {
      void loadStacks("poll");
    }, POLL_INTERVAL_MS);

    return () => {
      isMountedRef.current = false;
      window.clearInterval(intervalId);
      closeStackStream();
    };
  }, [loadStacks, closeStackStream]);

  useEffect(() => {
    if (!actionNotice || actionNotice.tone === "error") {
      return undefined;
    }
    const timeoutId = window.setTimeout(() => setActionNotice(null), 4500);
    return () => window.clearTimeout(timeoutId);
  }, [actionNotice]);

  const consoleTitle = consoleModal.action
    ? `${STACK_ACTION_META[consoleModal.action].label} ${consoleModal.stackName}`
    : consoleModal.stackName;

  return (
    <section className="space-y-4 sm:space-y-6">
      <PageHeader
        actions={
          <Button
            className="gap-2"
            disabled={isRefreshing}
            onClick={() => void loadStacks("manual")}
            variant="secondary"
          >
            <RefreshCw
              aria-hidden="true"
              className={cn("h-4 w-4", isRefreshing ? "animate-spin" : "")}
            />
            {isRefreshing ? "refreshing" : "refresh"}
          </Button>
        }
        description={`${stacks.length} stacks · synced ${lastUpdated}`}
        status={
          <StatusBadge
            label={`${stacks.filter((stack) => stack.status === "running").length} running`}
            tone="success"
          />
        }
        title="docker_stacks"
      />

      {actionNotice ? (
        <Card
          aria-live={actionNotice.tone === "error" ? "assertive" : "polite"}
          className={getNoticeToneClass(actionNotice.tone)}
          role="status"
        >
          <CardContent className="flex items-center gap-2 p-4 text-sm">
            {actionNotice.tone === "error" ? (
              <TriangleAlert aria-hidden="true" className="h-4 w-4" />
            ) : actionNotice.tone === "info" ? (
              <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
            ) : (
              <Activity aria-hidden="true" className="h-4 w-4" />
            )}
            {actionNotice.message}
          </CardContent>
        </Card>
      ) : null}

      {error && !stacks.length ? (
        <Card className="border-danger/30">
          <CardContent className="flex flex-col items-start gap-3 p-4 sm:p-6">
            <div className="flex items-center gap-2 text-danger">
              <TriangleAlert aria-hidden="true" className="h-4 w-4" />
              <p className="text-sm font-medium">Unable to load stacks</p>
            </div>
            <p className="text-sm text-muted-foreground">{error}</p>
            <Button onClick={() => void loadStacks("manual")} variant="outline">
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {error && stacks.length ? (
        <Card aria-live="polite" className="border-warning/30" role="status">
          <CardContent className="flex items-center gap-2 p-4 text-sm text-warning">
            <TriangleAlert aria-hidden="true" className="h-4 w-4" />
            Refresh failed: {error}
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
            Loading stacks...
          </CardContent>
        </Card>
      ) : null}

      {!isLoading && !error && !stacks.length ? (
        <Card>
          <CardContent className="flex min-h-[10rem] items-center justify-center p-6 text-sm text-muted-foreground">
            No stacks found.
          </CardContent>
        </Card>
      ) : null}

      {!isLoading && stacks.length ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {stacks.map((stack) => (
            <StackCard
              key={stack.name}
              onAction={onAction}
              onBackups={onBackups}
              onEdit={onEdit}
              onLogs={onLogs}
              pendingAction={pendingActions[stack.name]}
              stack={stack}
            />
          ))}
        </div>
      ) : null}

      {consoleModal.open ? (
        <ModalOverlay onClose={closeConsole}>
          <Card
            aria-labelledby="v2-stack-console-title"
            aria-modal="true"
            className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden"
            id="v2-stack-console"
            role="dialog"
          >
            <CardHeader className="flex flex-row items-start justify-between gap-3 border-b border-border/70 p-4 sm:p-5">
              <div className="space-y-1">
                <CardTitle
                  className="text-base sm:text-lg"
                  id="v2-stack-console-title"
                >
                  {consoleTitle}
                </CardTitle>
                <CardDescription>
                  {consoleModal.status === "streaming"
                    ? "Streaming docker compose output..."
                    : consoleModal.status === "error"
                      ? consoleModal.error || "Action failed"
                      : `Completed${consoleModal.returncode !== null ? ` (exit ${consoleModal.returncode})` : ""}`}
                </CardDescription>
              </div>
              <Button
                id="v2-stack-console-close"
                onClick={closeConsole}
                variant="outline"
              >
                Close
              </Button>
            </CardHeader>
            <CardContent className="p-0">
              <div className="max-h-[calc(90vh-6rem)] overflow-auto p-4">
                <pre
                  className="whitespace-pre-wrap break-words rounded-lg border border-border/70 bg-muted/25 p-3 text-xs sm:text-sm"
                  id="v2-stack-console-output"
                >
                  {consoleModal.lines.length
                    ? consoleModal.lines.join("\n")
                    : consoleModal.status === "streaming"
                      ? "Waiting for output..."
                      : consoleModal.error || "No output."}
                </pre>
              </div>
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}

      {logsModal.open ? (
        <ModalOverlay onClose={closeLogs}>
          <Card
            aria-labelledby="v2-stack-logs-title"
            aria-modal="true"
            className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden"
            id="v2-stack-logs-modal"
            role="dialog"
          >
            <CardHeader className="flex flex-row items-start justify-between gap-3 border-b border-border/70 p-4 sm:p-5">
              <div className="space-y-1">
                <CardTitle
                  className="text-base sm:text-lg"
                  id="v2-stack-logs-title"
                >
                  Stack Logs: {logsModal.stackName}
                </CardTitle>
                <CardDescription>
                  Tail output from `/api/stacks/&lt;name&gt;/logs`.
                </CardDescription>
              </div>
              <Button
                id="v2-stack-logs-close"
                onClick={closeLogs}
                variant="outline"
              >
                Close
              </Button>
            </CardHeader>
            <CardContent className="p-0">
              <div className="max-h-[calc(90vh-6rem)] overflow-auto p-4">
                <pre
                  className="whitespace-pre-wrap break-words rounded-lg border border-border/70 bg-muted/25 p-3 text-xs sm:text-sm"
                  id="v2-stack-logs-content"
                >
                  {logsModal.status === "loading"
                    ? "Loading logs..."
                    : logsModal.status === "error"
                      ? logsModal.error || "Failed to load logs"
                      : logsModal.logs || "No logs available."}
                </pre>
              </div>
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}

      {editorModal.open ? (
        <ModalOverlay onClose={closeEditor}>
          <Card
            aria-labelledby="v2-stack-editor-title"
            aria-modal="true"
            className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden"
            id="v2-stack-editor-modal"
            role="dialog"
          >
            <CardHeader className="flex flex-row items-start justify-between gap-3 border-b border-border/70 p-4 sm:p-5">
              <div className="space-y-1">
                <CardTitle
                  className="text-base sm:text-lg"
                  id="v2-stack-editor-title"
                >
                  Edit {editorModal.stackName}
                </CardTitle>
                <CardDescription>
                  {editorModal.tab === "compose"
                    ? editorModal.composeFilename || "docker-compose.yml"
                    : ".env"}
                </CardDescription>
              </div>
              <Button
                id="v2-stack-editor-close"
                onClick={closeEditor}
                variant="outline"
              >
                Close
              </Button>
            </CardHeader>
            <CardContent className="space-y-3 overflow-auto p-4">
              <div
                aria-label="Editor file"
                className="flex flex-wrap gap-2"
                role="group"
              >
                {(["compose", "env"] as EditorTab[]).map((tab) => (
                  <Button
                    aria-pressed={editorModal.tab === tab}
                    data-editor-tab={tab}
                    key={tab}
                    onClick={() =>
                      setEditorModal((current) => ({
                        ...current,
                        tab,
                        saveStatus: "idle",
                        saveError: null,
                      }))
                    }
                    size="sm"
                    variant={editorModal.tab === tab ? "default" : "outline"}
                  >
                    {tab === "compose" ? "Compose" : "Env"}
                  </Button>
                ))}
              </div>

              {editorModal.status === "loading" ? (
                <p className="text-sm text-muted-foreground">Loading...</p>
              ) : editorModal.status === "error" ? (
                <p className="text-sm text-danger">
                  {editorModal.loadError || "Failed to load files"}
                </p>
              ) : (
                <>
                  <textarea
                    aria-label={
                      editorModal.tab === "compose"
                        ? "Compose file content"
                        : "Env file content"
                    }
                    className="h-[40vh] w-full resize-y rounded-md border border-border bg-background p-3 font-mono text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm"
                    id="v2-stack-editor-textarea"
                    onChange={(event) =>
                      setEditorModal((current) => ({
                        ...current,
                        saveStatus: "idle",
                        saveError: null,
                        ...(current.tab === "compose"
                          ? { compose: event.target.value }
                          : { env: event.target.value }),
                      }))
                    }
                    spellCheck={false}
                    value={
                      editorModal.tab === "compose"
                        ? editorModal.compose
                        : editorModal.env
                    }
                  />
                  <div className="flex flex-wrap items-center gap-3">
                    <Button
                      disabled={editorModal.saveStatus === "saving"}
                      id="v2-stack-editor-save"
                      onClick={() => void saveEditor()}
                    >
                      {editorModal.saveStatus === "saving"
                        ? "Saving..."
                        : "Save"}
                    </Button>
                    <span
                      aria-live="polite"
                      className={cn(
                        "text-sm",
                        editorModal.saveStatus === "error"
                          ? "text-danger"
                          : "text-success",
                      )}
                      id="v2-stack-editor-status"
                      role="status"
                    >
                      {editorModal.saveStatus === "saved"
                        ? "Saved"
                        : editorModal.saveStatus === "error"
                          ? editorModal.saveError || "Save failed"
                          : ""}
                    </span>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}

      {backupsModal.open ? (
        <ModalOverlay onClose={closeBackups}>
          <Card
            aria-labelledby="v2-stack-backups-title"
            aria-modal="true"
            className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden"
            id="v2-stack-backups-modal"
            role="dialog"
          >
            <CardHeader className="flex flex-row items-start justify-between gap-3 border-b border-border/70 p-4 sm:p-5">
              <div className="space-y-1">
                <CardTitle
                  className="text-base sm:text-lg"
                  id="v2-stack-backups-title"
                >
                  Backups: {backupsModal.stackName}
                </CardTitle>
                <CardDescription>
                  Restore the compose file from a previous backup.
                </CardDescription>
              </div>
              <Button
                id="v2-stack-backups-close"
                onClick={closeBackups}
                variant="outline"
              >
                Close
              </Button>
            </CardHeader>
            <CardContent className="space-y-3 overflow-auto p-4">
              {backupsModal.notice ? (
                <p
                  aria-live="polite"
                  className="text-sm text-success"
                  role="status"
                >
                  {backupsModal.notice}
                </p>
              ) : null}
              {backupsModal.error ? (
                <p
                  aria-live="assertive"
                  className="text-sm text-danger"
                  role="status"
                >
                  {backupsModal.error}
                </p>
              ) : null}

              {backupsModal.status === "loading" ? (
                <p className="text-sm text-muted-foreground">
                  Loading backups...
                </p>
              ) : !backupsModal.backups.length ? (
                <p className="text-sm text-muted-foreground">
                  No backups available.
                </p>
              ) : (
                <ul className="space-y-2">
                  {backupsModal.backups.map((backup) => (
                    <li
                      className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-muted/20 p-3"
                      key={backup}
                    >
                      <span className="break-all font-mono text-xs sm:text-sm">
                        {backup}
                      </span>
                      {backupsModal.confirming === backup ? (
                        <span className="flex items-center gap-2">
                          <Button
                            className="border-danger/30 bg-danger/10 text-danger hover:bg-danger/15"
                            data-confirm-restore={backup}
                            disabled={backupsModal.restoring === backup}
                            onClick={() =>
                              void restoreBackup(backupsModal.stackName, backup)
                            }
                            size="sm"
                            variant="outline"
                          >
                            {backupsModal.restoring === backup
                              ? "Restoring..."
                              : "Confirm"}
                          </Button>
                          <Button
                            onClick={() =>
                              setBackupsModal((current) => ({
                                ...current,
                                confirming: null,
                              }))
                            }
                            size="sm"
                            variant="outline"
                          >
                            Cancel
                          </Button>
                        </span>
                      ) : (
                        <Button
                          data-restore={backup}
                          disabled={Boolean(backupsModal.restoring)}
                          onClick={() =>
                            setBackupsModal((current) => ({
                              ...current,
                              confirming: backup,
                              notice: null,
                              error: null,
                            }))
                          }
                          size="sm"
                          variant="outline"
                        >
                          Restore
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </ModalOverlay>
      ) : null}
    </section>
  );
}
