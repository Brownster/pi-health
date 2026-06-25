import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  Download,
  FileText,
  Layers,
  Loader2,
  Play,
  RefreshCw,
  RotateCw,
  Square,
  TriangleAlert,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import {
  type StackAction,
  type StackSummary,
  fetchStackLogs,
  fetchStacks,
  getStackServicesPercent,
  getStackStreamUrl,
  runStackAction,
} from "@/lib/stacks";
import { formatClockTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 10_000;

const ACTION_ORDER: StackAction[] = ["up", "down", "restart", "pull"];

const ACTION_META: Record<
  StackAction,
  { label: string; pendingLabel: string; className: string; Icon: typeof Play }
> = {
  up: {
    label: "Up",
    pendingLabel: "Starting...",
    className: "border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/15",
    Icon: Play,
  },
  down: {
    label: "Down",
    pendingLabel: "Stopping...",
    className: "border-rose-500/40 text-rose-300 hover:bg-rose-500/15",
    Icon: Square,
  },
  restart: {
    label: "Restart",
    pendingLabel: "Restarting...",
    className: "border-sky-500/40 text-sky-300 hover:bg-sky-500/15",
    Icon: RotateCw,
  },
  pull: {
    label: "Pull",
    pendingLabel: "Pulling...",
    className: "border-violet-500/40 text-violet-300 hover:bg-violet-500/15",
    Icon: Download,
  },
};

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

function getStatusTone(status: string): string {
  switch (status) {
    case "running":
      return "bg-emerald-500/15 text-emerald-300 border-emerald-500/40";
    case "stopped":
    case "exited":
      return "bg-rose-500/15 text-rose-300 border-rose-500/40";
    case "partial":
      return "bg-amber-500/15 text-amber-300 border-amber-500/40";
    default:
      return "bg-slate-500/15 text-slate-300 border-slate-500/40";
  }
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "Unable to complete the request";
}

function getNoticeToneClass(tone: ActionNotice["tone"]): string {
  if (tone === "success") {
    return "border-emerald-500/40 text-emerald-300";
  }
  if (tone === "error") {
    return "border-rose-500/40 text-rose-300";
  }
  return "border-sky-500/40 text-sky-300";
}

function StackCard({
  stack,
  pendingAction,
  onAction,
  onLogs,
}: {
  stack: StackSummary;
  pendingAction?: StackAction;
  onAction: (stack: StackSummary, action: StackAction) => void;
  onLogs: (stack: StackSummary) => void;
}) {
  const percent = getStackServicesPercent(stack);
  const running = stack.running_count ?? "—";
  const total = stack.container_count ?? "—";
  const rowBusy = Boolean(pendingAction);

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">{stack.name}</p>
            {stack.compose_file ? (
              <p className="truncate text-xs text-muted-foreground">{stack.compose_file}</p>
            ) : null}
          </div>
          <span
            className={cn(
              "shrink-0 rounded-full border px-2 py-1 text-xs font-medium capitalize",
              getStatusTone(stack.status),
            )}
          >
            {stack.status}
          </span>
        </div>

        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">
            {running} / {total} services up
          </p>
          <div className="h-1.5 rounded-full bg-muted">
            <div
              className="h-1.5 rounded-full bg-emerald-500 transition-[width] duration-300"
              style={{ width: `${percent ?? 0}%` }}
            />
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {ACTION_ORDER.map((action) => {
            const meta = ACTION_META[action];
            const isCurrent = pendingAction === action;
            const Icon = meta.Icon;
            return (
              <Button
                aria-label={`${meta.label} ${stack.name}`}
                className={cn("gap-1.5 px-2.5 text-xs sm:text-sm", meta.className)}
                data-action={action}
                data-stack={stack.name}
                disabled={rowBusy}
                key={action}
                onClick={() => onAction(stack, action)}
                size="sm"
                variant="outline"
              >
                {isCurrent ? (
                  <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Icon aria-hidden="true" className="h-3.5 w-3.5" />
                )}
                {isCurrent ? meta.pendingLabel : meta.label}
              </Button>
            );
          })}
          <Button
            aria-label={`Logs ${stack.name}`}
            className="gap-1.5 text-xs sm:text-sm"
            data-stack-action="logs"
            data-stack={stack.name}
            disabled={rowBusy}
            onClick={() => onLogs(stack)}
            size="sm"
            variant="outline"
          >
            <FileText aria-hidden="true" className="h-3.5 w-3.5" />
            Logs
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function StacksPage() {
  const [stacks, setStacks] = useState<StackSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState("Never");
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [pendingActions, setPendingActions] = useState<Record<string, StackAction>>({});
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

  const isMountedRef = useRef(true);
  const pendingActionsRef = useRef<Record<string, StackAction>>({});
  const eventSourceRef = useRef<EventSource | null>(null);

  const setPendingAction = useCallback((name: string, action: StackAction | null) => {
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
  }, []);

  const loadStacks = useCallback(async (reason: "initial" | "manual" | "poll" | "action") => {
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

  const closeEventSource = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const onAction = useCallback(
    (stack: StackSummary, action: StackAction) => {
      if (pendingActionsRef.current[stack.name]) {
        return;
      }

      const meta = ACTION_META[action];
      setPendingAction(stack.name, action);
      setActionNotice({ tone: "info", message: `${meta.pendingLabel.replace("...", "")} ${stack.name}...` });
      setConsoleModal({
        open: true,
        stackName: stack.name,
        action,
        status: "streaming",
        lines: [],
        returncode: null,
        error: null,
      });

      let doneReceived = false;

      const finish = () => {
        closeEventSource();
        if (isMountedRef.current) {
          setPendingAction(stack.name, null);
        }
        void loadStacks("action");
      };

      const fallbackToPost = async () => {
        try {
          const result = await runStackAction(stack.name, action);
          if (!isMountedRef.current) {
            return;
          }
          const output = [result.stdout, result.stderr]
            .filter((part) => part && part.trim().length > 0)
            .join("\n")
            .trim();
          const failed = result.success === false;
          setConsoleModal((current) => ({
            ...current,
            status: failed ? "error" : "done",
            lines: output ? output.split("\n") : current.lines,
            returncode: result.returncode ?? null,
            error: failed ? `Command exited with code ${result.returncode}` : null,
          }));
          setActionNotice({
            tone: failed ? "error" : "success",
            message: failed
              ? `${meta.label} failed for ${stack.name}`
              : `${meta.label} completed for ${stack.name}`,
          });
        } catch (caughtError) {
          if (!isMountedRef.current) {
            return;
          }
          setConsoleModal((current) => ({ ...current, status: "error", error: getErrorMessage(caughtError) }));
          setActionNotice({ tone: "error", message: `${meta.label} failed for ${stack.name}: ${getErrorMessage(caughtError)}` });
        } finally {
          finish();
        }
      };

      let source: EventSource;
      try {
        source = new EventSource(getStackStreamUrl(stack.name, action));
      } catch {
        void fallbackToPost();
        return;
      }
      eventSourceRef.current = source;

      source.onmessage = (event) => {
        let data: { line?: string; done?: boolean; returncode?: number; error?: string };
        try {
          data = JSON.parse(event.data);
        } catch {
          return;
        }
        if (!isMountedRef.current) {
          return;
        }

        if (data.error) {
          doneReceived = true;
          setConsoleModal((current) => ({ ...current, status: "error", error: data.error ?? "Stream error" }));
          setActionNotice({ tone: "error", message: `${meta.label} failed for ${stack.name}` });
          finish();
          return;
        }
        if (data.done) {
          doneReceived = true;
          const failed = typeof data.returncode === "number" && data.returncode !== 0;
          setConsoleModal((current) => ({
            ...current,
            status: failed ? "error" : "done",
            returncode: data.returncode ?? null,
            error: failed ? `Command exited with code ${data.returncode}` : null,
          }));
          setActionNotice({
            tone: failed ? "error" : "success",
            message: failed
              ? `${meta.label} failed for ${stack.name}`
              : `${meta.label} completed for ${stack.name}`,
          });
          finish();
          return;
        }
        if (typeof data.line === "string") {
          setConsoleModal((current) => ({ ...current, lines: [...current.lines, data.line as string] }));
        }
      };

      source.onerror = () => {
        if (doneReceived) {
          // Normal close after the server finished the stream.
          return;
        }
        // Stream unavailable/interrupted before completion: fall back to the POST action.
        closeEventSource();
        void fallbackToPost();
      };
    },
    [closeEventSource, loadStacks, setPendingAction],
  );

  const closeConsole = useCallback(() => {
    setConsoleModal((current) => {
      if (current.status === "streaming") {
        // User dismissed mid-run: stop listening and release the row lock.
        closeEventSource();
        if (current.stackName) {
          setPendingAction(current.stackName, null);
        }
      }
      return { ...current, open: false };
    });
  }, [closeEventSource, setPendingAction]);

  const onLogs = useCallback(async (stack: StackSummary) => {
    setLogsModal({ open: true, status: "loading", stackName: stack.name, logs: "", error: null });
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

  useEffect(() => {
    isMountedRef.current = true;
    void loadStacks("initial");

    const intervalId = window.setInterval(() => {
      void loadStacks("poll");
    }, POLL_INTERVAL_MS);

    return () => {
      isMountedRef.current = false;
      window.clearInterval(intervalId);
      closeEventSource();
    };
  }, [loadStacks, closeEventSource]);

  useEffect(() => {
    if (!actionNotice || actionNotice.tone === "error") {
      return undefined;
    }
    const timeoutId = window.setTimeout(() => setActionNotice(null), 4500);
    return () => window.clearTimeout(timeoutId);
  }, [actionNotice]);

  const consoleTitle = consoleModal.action
    ? `${ACTION_META[consoleModal.action].label} ${consoleModal.stackName}`
    : consoleModal.stackName;

  return (
    <section className="space-y-4 sm:space-y-6">
      <Card>
        <CardHeader className="space-y-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0 space-y-1">
              <CardTitle className="flex items-center gap-2 text-lg sm:text-xl">
                <Layers aria-hidden="true" className="h-5 w-5 text-primary" />
                Docker Stacks
              </CardTitle>
              <CardDescription>Compose stacks discovered on the host.</CardDescription>
            </div>
            <span className="inline-flex min-h-11 items-center rounded-md border border-border bg-muted/70 px-3 text-xs text-muted-foreground">
              Last updated: {lastUpdated}
            </span>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              className="gap-2"
              disabled={isRefreshing}
              onClick={() => void loadStacks("manual")}
              variant="outline"
            >
              <RefreshCw aria-hidden="true" className={cn("h-4 w-4", isRefreshing ? "animate-spin" : "")} />
              {isRefreshing ? "Refreshing" : "Refresh"}
            </Button>
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
        <Card className="border-rose-500/40">
          <CardContent className="flex flex-col items-start gap-3 p-4 sm:p-6">
            <div className="flex items-center gap-2 text-rose-300">
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
        <Card aria-live="polite" className="border-amber-500/40" role="status">
          <CardContent className="flex items-center gap-2 p-4 text-sm text-amber-300">
            <TriangleAlert aria-hidden="true" className="h-4 w-4" />
            Refresh failed: {error}
          </CardContent>
        </Card>
      ) : null}

      {isLoading ? (
        <Card aria-live="polite" role="status">
          <CardContent className="flex min-h-[14rem] items-center justify-center gap-2 p-6 text-sm text-muted-foreground">
            <Activity aria-hidden="true" className="h-4 w-4 animate-pulse text-primary" />
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
                <CardTitle className="text-base sm:text-lg" id="v2-stack-console-title">
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
              <Button id="v2-stack-console-close" onClick={closeConsole} variant="outline">
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
                <CardTitle className="text-base sm:text-lg" id="v2-stack-logs-title">
                  Stack Logs: {logsModal.stackName}
                </CardTitle>
                <CardDescription>Tail output from `/api/stacks/&lt;name&gt;/logs`.</CardDescription>
              </div>
              <Button id="v2-stack-logs-close" onClick={closeLogs} variant="outline">
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
    </section>
  );
}
