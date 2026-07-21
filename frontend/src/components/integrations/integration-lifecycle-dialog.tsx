import { useId, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  RefreshCw,
  TriangleAlert,
  X,
} from "lucide-react";

import type { LifecycleDialogState } from "@/components/integrations/use-integration-lifecycle";
import { Button } from "@/components/ui/button";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import { cn } from "@/lib/utils";

const FIELD_CLASS = "min-h-11 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function IntegrationLifecycleDialog({
  acknowledgement,
  children,
  confirmLabel,
  confirmation,
  description,
  destructive = false,
  onClose,
  onConfirm,
  onRetry,
  ready = true,
  restoreFocus,
  state,
  title,
}: {
  acknowledgement?: string;
  children?: ReactNode;
  confirmLabel: string;
  confirmation?: { expected: string; label?: string };
  description: string;
  destructive?: boolean;
  onClose: () => void;
  onConfirm: (values: { confirmation?: string; acknowledged: boolean }) => void;
  onRetry?: () => void;
  ready?: boolean;
  restoreFocus?: () => void;
  state: LifecycleDialogState;
  title: string;
}) {
  const titleId = useId();
  const statusId = useId();
  const [confirmationValue, setConfirmationValue] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const running = state.phase === "running";
  const canConfirm = ready
    && (!confirmation || confirmationValue === confirmation.expected)
    && (!acknowledgement || acknowledged);
  const close = () => {
    if (running) return;
    setConfirmationValue("");
    setAcknowledged(false);
    onClose();
  };

  return (
    <ModalOverlay onClose={running ? () => undefined : close} restoreFocus={restoreFocus}>
      <div
        aria-describedby={statusId}
        aria-labelledby={titleId}
        aria-modal="true"
        className="flex max-h-[92vh] w-full max-w-xl flex-col overflow-hidden rounded-lg border border-border bg-card"
        data-integration-lifecycle-dialog
        role="dialog"
      >
        <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-4 sm:px-5">
          <div className="min-w-0">
            <h2 className="font-mono text-base font-semibold" id={titleId}>{title}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{description}</p>
          </div>
          <Button aria-label="Close dialog" className="h-11 w-11 shrink-0 px-0" disabled={running} onClick={close} variant="ghost">
            <X aria-hidden="true" className="h-4 w-4" />
          </Button>
        </header>

        <div className="space-y-4 overflow-y-auto px-4 py-5 sm:px-5">
          {state.phase === "confirm" ? (
            <>
              <div className={cn("flex items-start gap-2 border-l-2 px-3 py-2.5 text-sm", destructive ? "border-danger bg-danger/5 text-danger" : "border-warning bg-warning/5 text-warning")}>
                <AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
                <p id={statusId}>{destructive ? "Review the consequences before continuing." : "The integration state will change immediately."}</p>
              </div>
              {children}
              {confirmation ? (
                <label className="block space-y-1.5">
                  <span className="text-sm text-foreground">{confirmation.label ?? "Type"} <code className={destructive ? "text-danger" : "text-warning"}>{confirmation.expected}</code> to confirm</span>
                  <input
                    autoComplete="off"
                    className={FIELD_CLASS}
                    data-lifecycle-confirmation
                    onChange={(event) => setConfirmationValue(event.target.value)}
                    spellCheck={false}
                    value={confirmationValue}
                  />
                </label>
              ) : null}
              {acknowledgement ? (
                <label className="flex min-h-11 items-start gap-3 rounded-md border border-border bg-muted/20 px-3 py-2.5 text-sm">
                  <input
                    checked={acknowledged}
                    className="mt-0.5 h-5 w-5 shrink-0 accent-primary"
                    data-lifecycle-acknowledgement
                    onChange={(event) => setAcknowledged(event.target.checked)}
                    type="checkbox"
                  />
                  <span>{acknowledgement}</span>
                </label>
              ) : null}
              <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4">
                <Button onClick={close} variant="outline">Cancel</Button>
                <Button
                  data-lifecycle-confirm
                  disabled={!canConfirm}
                  onClick={() => onConfirm({
                    ...(confirmation ? { confirmation: confirmationValue } : {}),
                    acknowledged,
                  })}
                  variant={destructive ? "danger" : "warning"}
                >
                  {confirmLabel}
                </Button>
              </div>
            </>
          ) : (
            <>
              <div
                aria-live="polite"
                className={cn(
                  "flex items-start gap-2 border-l-2 px-3 py-2.5 text-sm",
                  running && "border-info bg-info/5 text-info",
                  state.phase === "success" && "border-success bg-success/5 text-success",
                  state.phase === "warning" && "border-warning bg-warning/5 text-warning",
                  state.phase === "error" && "border-danger bg-danger/5 text-danger",
                )}
                id={statusId}
                role={state.phase === "error" ? "alert" : "status"}
              >
                {running ? <Loader2 aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 animate-spin" /> : null}
                {state.phase === "success" ? <CheckCircle2 aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" /> : null}
                {state.phase === "warning" ? <AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" /> : null}
                {state.phase === "error" ? <TriangleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" /> : null}
                <p>
                  {running ? "Operation in progress" : null}
                  {state.phase === "success" ? "Operation completed" : null}
                  {state.phase === "warning" ? "Operation completed with attention needed" : null}
                  {state.phase === "error" ? state.error ?? "Lifecycle operation failed" : null}
                </p>
              </div>

              {state.lines.length ? (
                <ol className="max-h-64 space-y-1 overflow-y-auto rounded-md border border-border bg-black/30 p-3 font-mono text-xs leading-5 text-muted-foreground" data-lifecycle-progress>
                  {state.lines.map((line, index) => <li className="break-words whitespace-pre-wrap" key={`${index}:${line}`}>{line}</li>)}
                </ol>
              ) : null}

              {state.warnings.length ? (
                <ul className="space-y-2" data-lifecycle-warnings>
                  {state.warnings.map((warning) => (
                    <li className="break-words border-l-2 border-warning bg-warning/5 px-3 py-2 text-sm text-warning" key={warning.code}>{warning.message}</li>
                  ))}
                </ul>
              ) : null}

              {!running ? (
                <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4">
                  {state.phase === "error" && onRetry ? (
                    <Button className="gap-2" data-lifecycle-retry onClick={onRetry} variant="warning">
                      <RefreshCw aria-hidden="true" className="h-4 w-4" />Retry
                    </Button>
                  ) : null}
                  <Button onClick={close} variant="outline">Close</Button>
                </div>
              ) : null}
            </>
          )}
        </div>
      </div>
    </ModalOverlay>
  );
}
