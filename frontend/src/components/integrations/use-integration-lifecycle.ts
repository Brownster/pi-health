import { useCallback, useRef, useState } from "react";

import { lifecycleWarnings, type IntegrationLifecycleWarning } from "@/lib/integration-lifecycle-contract";
import type { OperationEvent } from "@/lib/operations";

export type LifecycleDialogPhase = "confirm" | "running" | "success" | "warning" | "error";
export type LifecycleExecutor = (onEvent: (event: OperationEvent) => void) => Promise<void>;

export interface LifecycleDialogState {
  open: boolean;
  phase: LifecycleDialogPhase;
  lines: string[];
  error: string | null;
  warnings: IntegrationLifecycleWarning[];
}

const CLOSED_STATE: LifecycleDialogState = {
  open: false,
  phase: "confirm",
  lines: [],
  error: null,
  warnings: [],
};

function publicError(error: unknown): string {
  return error instanceof Error ? error.message : "Lifecycle operation failed";
}

export function useIntegrationLifecycle(onInvalidated: () => void) {
  const [state, setState] = useState<LifecycleDialogState>(CLOSED_STATE);
  const executorRef = useRef<LifecycleExecutor | null>(null);

  const open = useCallback(() => {
    executorRef.current = null;
    setState({ ...CLOSED_STATE, open: true });
  }, []);

  const close = useCallback(() => {
    setState((current) => current.phase === "running" ? current : CLOSED_STATE);
  }, []);

  const reconfirm = useCallback(() => {
    executorRef.current = null;
    setState({ ...CLOSED_STATE, open: true });
  }, []);

  const run = useCallback(async (executor: LifecycleExecutor): Promise<boolean> => {
    executorRef.current = executor;
    let terminalWarnings: IntegrationLifecycleWarning[] = [];
    setState((current) => ({
      ...current,
      open: true,
      phase: "running",
      lines: [],
      error: null,
      warnings: [],
    }));
    try {
      await executor((event) => {
        const warnings = lifecycleWarnings(event.warnings);
        if (warnings.length) terminalWarnings = warnings;
        setState((current) => ({
          ...current,
          lines: event.line
            ? [...current.lines, event.line].slice(-100)
            : current.lines,
          warnings: warnings.length ? warnings : current.warnings,
        }));
      });
      setState((current) => ({
        ...current,
        phase: terminalWarnings.length ? "warning" : "success",
        warnings: terminalWarnings,
      }));
      return true;
    } catch (error) {
      setState((current) => ({
        ...current,
        phase: "error",
        error: publicError(error),
      }));
      return false;
    } finally {
      onInvalidated();
    }
  }, [onInvalidated]);

  const retry = useCallback(async (): Promise<boolean> => {
    return executorRef.current ? run(executorRef.current) : false;
  }, [run]);

  return { state, open, close, reconfirm, run, retry };
}
