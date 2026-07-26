import { useCallback, useEffect, useState } from "react";
import { RotateCw, TriangleAlert, X } from "lucide-react";

import {
  type PendingAction,
  dismissPendingAction,
  fetchPendingActions,
} from "@/lib/pending-actions";
import { cn } from "@/lib/utils";

// Long: these outlive restarts and change only when an update or a reboot happens.
const POLL_INTERVAL_MS = 120_000;

const TONES = {
  critical: "border-danger/60 bg-danger/[0.06] text-danger",
  attention: "border-warning/60 bg-warning/[0.06] text-warning",
  info: "border-info/60 bg-info/[0.06] text-info",
} as const;

function ActionRow({
  action,
  onDismiss,
}: {
  action: PendingAction;
  onDismiss: (actionId: string) => void;
}) {
  const Icon = action.id === "reboot_required" ? RotateCw : TriangleAlert;
  return (
    <div
      className={cn("flex items-start gap-3 border-l-2 px-4 py-3", TONES[action.severity])}
      role="status"
    >
      <Icon aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{action.title}</p>
        {action.detail ? (
          <p className="mt-0.5 text-sm text-muted-foreground">{action.detail}</p>
        ) : null}
        {action.command ? (
          <p className="mt-1.5 font-mono text-xs text-muted-foreground">
            <code className="rounded bg-muted px-1.5 py-0.5 text-foreground">
              {action.command}
            </code>
          </p>
        ) : null}
      </div>
      <button
        aria-label={`Dismiss: ${action.title}`}
        className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => onDismiss(action.id)}
        title="Dismiss"
        type="button"
      >
        <X aria-hidden="true" className="h-4 w-4" />
      </button>
    </div>
  );
}

/**
 * Shows work LimeOS finished setting up but cannot complete itself — a reboot,
 * most often. The update that raises one of these also restarts the service, so
 * the notice has to come from the server rather than from update-page state.
 */
export function PendingActionsBanner() {
  const [actions, setActions] = useState<PendingAction[]>([]);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const next = await fetchPendingActions(signal);
      if (!signal?.aborted) {
        setActions(next);
      }
    } catch {
      // A banner that cannot load is simply not shown.
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    const intervalId = window.setInterval(() => void load(controller.signal), POLL_INTERVAL_MS);
    return () => {
      controller.abort();
      window.clearInterval(intervalId);
    };
  }, [load]);

  const onDismiss = useCallback(async (actionId: string) => {
    setActions((current) => current.filter((action) => action.id !== actionId));
    try {
      await dismissPendingAction(actionId);
    } catch {
      // The server keeps it; the next poll brings it back.
    }
  }, []);

  if (!actions.length) {
    return null;
  }

  return (
    <div className="mb-4 space-y-2 sm:mb-5">
      {actions.map((action) => (
        <ActionRow action={action} key={action.id} onDismiss={onDismiss} />
      ))}
    </div>
  );
}
