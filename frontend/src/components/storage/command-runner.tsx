import { useState } from "react";
import { AlertTriangle, Play, Terminal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { MetricBar } from "@/components/ui/metric-bar";
import { cn } from "@/lib/utils";
import {
  streamPluginCommand,
  type PluginCommand,
  type PluginCommandParam,
} from "@/lib/storage-plugins";

interface Progress {
  percent: number | null;
  eta: number | null;
  speed: number | null;
}

interface RunState {
  commandId: string | null;
  running: boolean;
  lines: string[];
  progress: Progress | null;
  errors: string[];
  summary: { success: boolean; message: string; data: Record<string, unknown> | null } | null;
  transportError: string | null;
  forceAvailable: boolean;
}

const EMPTY_RUN: RunState = {
  commandId: null,
  running: false,
  lines: [],
  progress: null,
  errors: [],
  summary: null,
  transportError: null,
  forceAvailable: false,
};

function num(value: string, fallback: number | null): number | null {
  if (value.trim() === "") {
    return fallback;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function formatEta(seconds: number | null): string {
  if (seconds == null || seconds <= 0) {
    return "";
  }
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m ? `~${m}m ${s}s left` : `~${s}s left`;
}

export function CommandRunner({
  pluginId,
  commands,
  poolNames,
  onCompleted,
}: {
  pluginId: string;
  commands: PluginCommand[];
  poolNames: string[];
  onCompleted?: () => void;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [values, setValues] = useState<Record<string, Record<string, string>>>({});
  const [run, setRun] = useState<RunState>(EMPTY_RUN);

  const setValue = (commandId: string, name: string, value: string) => {
    setValues((prev) => ({ ...prev, [commandId]: { ...prev[commandId], [name]: value } }));
  };

  const paramValue = (command: PluginCommand, param: PluginCommandParam): string => {
    const current = values[command.id]?.[param.name];
    if (current !== undefined) {
      return current;
    }
    if (param.type === "select" && param.source?.includes("pools") && poolNames.length) {
      return poolNames[0];
    }
    if (param.default !== undefined && param.default !== null) {
      return String(param.default);
    }
    return "";
  };

  const buildParams = (command: PluginCommand): Record<string, unknown> => {
    const params: Record<string, unknown> = {};
    for (const param of command.param_schema ?? []) {
      const raw = paramValue(command, param);
      if (param.type === "number") {
        const parsed = num(raw, typeof param.default === "number" ? param.default : null);
        if (parsed !== null) {
          params[param.name] = parsed;
        }
      } else if (raw !== "") {
        params[param.name] = raw;
      }
    }
    return params;
  };

  const missingRequired = (command: PluginCommand): boolean =>
    (command.param_schema ?? []).some(
      (param) => param.required && paramValue(command, param) === "",
    );

  async function execute(command: PluginCommand, extra?: Record<string, unknown>) {
    setConfirming(false);
    setRun({ ...EMPTY_RUN, commandId: command.id, running: true });
    try {
      const params = { ...buildParams(command), ...(extra ?? {}) };
      await streamPluginCommand(pluginId, command.id, params, (event) => {
        setRun((current) => {
          if (event.type === "output" && typeof event.line === "string") {
            return { ...current, lines: [...current.lines, event.line] };
          }
          if (event.type === "tag") {
            if (event.name === "run" && event.values?.[0] === "pos") {
              // Tag values arrive as strings (from the log-tag parser); coerce.
              const toNum = (x: unknown) => {
                const n = Number(x);
                return Number.isFinite(n) ? n : null;
              };
              const v = event.values;
              return {
                ...current,
                progress: { percent: toNum(v[4]), eta: toNum(v[5]), speed: toNum(v[6]) },
              };
            }
            if (event.name === "msg" && (event.values?.[0] === "error" || event.values?.[0] === "fatal")) {
              return { ...current, errors: [...current.errors, String(event.values[1] ?? "")] };
            }
            return current;
          }
          if (event.type === "complete") {
            const data = (event.data as Record<string, unknown>) ?? null;
            return {
              ...current,
              running: false,
              forceAvailable: !event.success && data?.force_allowed === true,
              summary: {
                success: Boolean(event.success),
                message: String(event.message || event.error || ""),
                data,
              },
            };
          }
          if (event.type === "error") {
            return { ...current, running: false, transportError: event.error ?? "Command error" };
          }
          return current;
        });
      });
      onCompleted?.();
    } catch (error) {
      setRun((current) => ({
        ...current,
        running: false,
        transportError: error instanceof Error ? error.message : "Could not start command",
      }));
    } finally {
      setRun((current) => ({ ...current, running: false }));
    }
  }

  const openCommand = openId ? commands.find((c) => c.id === openId) ?? null : null;

  return (
    <div className="space-y-3">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">Commands</p>
      <div className="flex flex-wrap gap-2">
        {commands.map((command) => (
          <Button
            className="gap-1.5 text-xs sm:text-sm"
            data-plugin-command={command.id}
            disabled={run.running}
            key={command.id}
            onClick={() => {
              setConfirming(false);
              const hasParams = (command.param_schema ?? []).length > 0;
              if (command.dangerous || hasParams) {
                // Open a panel for the param form and/or the confirmation step.
                const nextOpen = openId === command.id ? null : command.id;
                setOpenId(nextOpen);
                if (nextOpen && command.dangerous && !hasParams) {
                  setConfirming(true);
                }
              } else {
                // Safe, parameter-less command: run immediately.
                setOpenId(null);
                void execute(command);
              }
            }}
            size="sm"
            variant={openId === command.id ? "default" : "outline"}
          >
            <Terminal aria-hidden="true" className="h-3.5 w-3.5" />
            {command.label}
            {command.dangerous ? " ⚠" : ""}
          </Button>
        ))}
      </div>

      {openCommand ? (
        <div className="space-y-3 rounded-lg border border-border/70 bg-muted/20 p-3">
          {(openCommand.param_schema ?? []).map((param) => (
            <label className="block space-y-1 text-xs" key={param.name}>
              <span className="text-muted-foreground">{param.label ?? param.name}</span>
              {param.type === "select" ? (
                <select
                  className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                  data-command-param={param.name}
                  disabled={!poolNames.length}
                  onChange={(e) => setValue(openCommand.id, param.name, e.target.value)}
                  value={paramValue(openCommand, param)}
                >
                  {poolNames.length ? (
                    poolNames.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))
                  ) : (
                    <option value="">No pools configured</option>
                  )}
                </select>
              ) : (
                <input
                  className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                  data-command-param={param.name}
                  max={param.max}
                  min={param.min}
                  onChange={(e) => setValue(openCommand.id, param.name, e.target.value)}
                  type={param.type === "number" ? "number" : "text"}
                  value={paramValue(openCommand, param)}
                />
              )}
            </label>
          ))}

          {confirming && openCommand.dangerous ? (
            <div className="space-y-2 rounded-md border border-danger/40 bg-danger/10 p-3 text-xs">
              <p className="flex items-center gap-1.5 font-medium text-danger">
                <AlertTriangle aria-hidden="true" className="h-4 w-4" />
                This can modify or delete data. Continue?
              </p>
              <div className="flex gap-2">
                <Button
                  data-command-confirm={openCommand.id}
                  onClick={() => void execute(openCommand)}
                  size="sm"
                  variant="danger"
                >
                  Run {openCommand.label}
                </Button>
                <Button onClick={() => setConfirming(false)} size="sm" variant="outline">
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <Button
              className="gap-1.5"
              data-command-run={openCommand.id}
              disabled={run.running || missingRequired(openCommand)}
              onClick={() =>
                openCommand.dangerous ? setConfirming(true) : void execute(openCommand)
              }
              size="sm"
            >
              <Play aria-hidden="true" className="h-3.5 w-3.5" />
              Run {openCommand.label}
            </Button>
          )}
        </div>
      ) : null}

      {run.commandId ? (
        <div className="space-y-2 rounded-lg border border-border/70 bg-muted/20 p-3" data-command-output>
          {run.transportError ? (
            <p
              className="flex items-center gap-1.5 rounded-md bg-danger/10 px-2 py-1.5 text-xs font-medium text-danger"
              data-command-transport-error
            >
              <AlertTriangle aria-hidden="true" className="h-4 w-4" />
              Couldn&apos;t start: {run.transportError}
            </p>
          ) : null}

          {run.progress ? (
            <div className="space-y-1" data-command-progress>
              <MetricBar
                label="command progress"
                tone="primary"
                value={run.progress.percent}
              />
              <p className="text-[0.7rem] text-muted-foreground tabular-nums">
                {run.progress.percent != null ? `${run.progress.percent}%` : "running"}
                {formatEta(run.progress.eta) ? ` · ${formatEta(run.progress.eta)}` : ""}
                {run.progress.speed ? ` · ${run.progress.speed.toFixed(1)} MB/s` : ""}
              </p>
            </div>
          ) : null}

          {run.errors.length ? (
            <ul className="space-y-1" data-command-errors>
              {run.errors.map((message, index) => (
                <li className="text-xs font-medium text-danger" key={index}>
                  {message}
                </li>
              ))}
            </ul>
          ) : null}

          {run.summary ? (
            <div
              className={cn(
                "rounded-md px-2 py-1.5 text-xs font-medium",
                run.summary.success ? "bg-success/10 text-success" : "bg-danger/10 text-danger",
              )}
              data-command-summary
            >
              {run.summary.success ? "Completed" : "Failed"}
              {run.summary.message ? `: ${run.summary.message}` : ""}
              {run.summary.data
                ? ` (${Object.entries(run.summary.data)
                    .filter(([, v]) => typeof v === "number")
                    .map(([k, v]) => `${v} ${k}`)
                    .join(", ")})`
                : ""}
            </div>
          ) : null}

          {run.forceAvailable ? (
            <div
              className="space-y-2 rounded-md border border-danger/40 bg-danger/10 p-2 text-xs"
              data-command-threshold
            >
              <p className="font-medium text-danger">
                This exceeds the configured safety threshold (see the counts above). Run anyway?
              </p>
              <Button
                data-command-force
                onClick={() => {
                  const command = commands.find((c) => c.id === run.commandId);
                  if (command) {
                    void execute(command, {
                      force: true,
                      force_reason: "operator confirmed threshold override",
                    });
                  }
                }}
                size="sm"
                variant="danger"
              >
                Run anyway
              </Button>
            </div>
          ) : null}

          <pre
            className="max-h-[20vh] overflow-auto whitespace-pre-wrap break-words text-xs sm:text-sm"
            id="v2-plugin-command-output"
          >
            {run.lines.join("\n") || (run.running ? "Waiting for output..." : "")}
          </pre>
        </div>
      ) : null}
    </div>
  );
}
