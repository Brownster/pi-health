import { useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Play,
  Stethoscope,
  Terminal,
  Trash2,
  X,
} from "lucide-react";

import { SchemaField } from "@/components/capabilities/schema-field";
import { Button, type ButtonProps } from "@/components/ui/button";
import { MetricBar } from "@/components/ui/metric-bar";
import { ModalOverlay } from "@/components/ui/modal-overlay";
import type {
  CapabilityAction,
  CapabilityActionCatalog,
  CapabilityActionEvent,
  CapabilityStatus,
} from "@/lib/capabilities";
import {
  actionParameterAsField,
  actionParameterChoices,
  initialActionRunState,
  reduceActionEvent,
  setupInitialValues,
  type CapabilityActionRunState,
  type CapabilityFormValues,
  validateSetupValues,
} from "@/lib/capability-renderer";
import { cn } from "@/lib/utils";

export interface CapabilityActionRequest {
  action_id: string;
  parameters: CapabilityFormValues;
}

export type CapabilityActionExecutor = (
  request: CapabilityActionRequest,
  onEvent: (event: CapabilityActionEvent) => void,
) => Promise<CapabilityActionEvent | void>;

function actionVariant(intent: CapabilityAction["intent"]): ButtonProps["variant"] {
  if (intent === "destructive") return "danger";
  if (intent === "mutation") return "warning";
  if (intent === "diagnostic") return "info";
  return "outline";
}

function ActionIcon({ intent }: { intent: CapabilityAction["intent"] }) {
  if (intent === "destructive") return <Trash2 aria-hidden="true" className="h-4 w-4" />;
  if (intent === "diagnostic") return <Stethoscope aria-hidden="true" className="h-4 w-4" />;
  return <Play aria-hidden="true" className="h-4 w-4" />;
}

function publicActionError(error: unknown): string {
  const message = error instanceof Error ? error.message : "Action could not be started.";
  return message.replace(/\s+/g, " ").trim().slice(0, 240) || "Action could not be started.";
}

export function CapabilityActions({
  catalog,
  status,
  execute,
}: {
  catalog: CapabilityActionCatalog;
  status: CapabilityStatus;
  execute: CapabilityActionExecutor;
}) {
  const [selected, setSelected] = useState<CapabilityAction | null>(null);
  const [draft, setDraft] = useState<CapabilityFormValues>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [run, setRun] = useState<CapabilityActionRunState>(initialActionRunState);
  const [runningAction, setRunningAction] = useState<string | null>(null);
  const availability = useMemo(
    () => new Map(catalog.availability.map((item) => [item.id, item])),
    [catalog],
  );
  const dialogTitleId = `${catalog.provider_id}-${catalog.capability_id.split(".").join("-")}-action-dialog-title`;

  function unavailableReason(action: CapabilityAction): string | null {
    const reported = availability.get(action.id);
    if (!reported) return "Availability was not reported.";
    if (!reported.available) return reported.unavailable_reason ?? "Action is unavailable.";
    if (
      (action.intent === "mutation" || action.intent === "destructive") &&
      !action.confirmation
    ) {
      return "Confirmation is unavailable.";
    }
    return null;
  }

  function openAction(action: CapabilityAction) {
    const fields = action.parameters.map((parameter) =>
      actionParameterAsField(parameter, actionParameterChoices(parameter, status)),
    );
    if (!fields.length && !action.confirmation) {
      void runAction(action, {});
      return;
    }
    setSelected(action);
    setDraft(
      setupInitialValues(
        {
          schema_version: "1",
          schema_id: `${catalog.provider_id}-${action.id}-v1`,
          title: action.label,
          fields,
        },
      ),
    );
    setFieldErrors({});
  }

  async function runAction(action: CapabilityAction, values: CapabilityFormValues) {
    setSelected(null);
    setRunningAction(action.id);
    setRun({ ...initialActionRunState(), phase: "running" });
    try {
      const finalEvent = await execute(
        { action_id: action.id, parameters: values },
        (event) => setRun((current) => reduceActionEvent(current, event)),
      );
      if (finalEvent) {
        setRun((current) => reduceActionEvent(current, finalEvent));
      }
      setRun((current) =>
        current.phase === "running"
          ? {
              ...current,
              phase: "error",
              success: false,
              message: "Action ended before reporting a result.",
            }
          : current,
      );
    } catch (error) {
      setRun((current) => ({
        ...current,
        phase: "error",
        success: false,
        message: publicActionError(error),
      }));
    } finally {
      setRunningAction(null);
    }
  }

  function submitSelected() {
    if (!selected) return;
    const fields = selected.parameters.map((parameter) =>
      actionParameterAsField(parameter, actionParameterChoices(parameter, status)),
    );
    const validation = validateSetupValues(fields, draft);
    setFieldErrors(
      Object.fromEntries(validation.errors.map((error) => [error.field, error.message])),
    );
    if (!validation.errors.length) void runAction(selected, validation.values);
  }

  return (
    <section aria-labelledby={`${catalog.provider_id}-actions-title`} className="rounded-lg border border-border bg-card">
      <header className="border-b border-border px-4 py-4 sm:px-5">
        <h2 className="font-mono text-sm font-semibold" id={`${catalog.provider_id}-actions-title`}>
          Actions
        </h2>
      </header>
      <div className="space-y-4 px-4 py-5 sm:px-5">
        <div className="flex flex-wrap gap-2">
          {catalog.actions.map((action) => {
            const reason = unavailableReason(action);
            const disabled = runningAction !== null || reason !== null;
            return (
              <Button
                aria-label={action.label}
                className="gap-2"
                disabled={disabled}
                key={action.id}
                onClick={() => openAction(action)}
                title={reason ?? action.description}
                variant={actionVariant(action.intent)}
              >
                {runningAction === action.id ? (
                  <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                ) : (
                  <ActionIcon intent={action.intent} />
                )}
                {action.label}
              </Button>
            );
          })}
        </div>

        {catalog.actions.some((action) => unavailableReason(action) !== null) ? (
          <ul className="space-y-1 text-xs text-muted-foreground">
            {catalog.actions
              .filter((action) => unavailableReason(action) !== null)
              .map((action) => {
                return (
                  <li key={action.id}>
                    <span className="text-foreground">{action.label}:</span>{" "}
                    {unavailableReason(action)}
                  </li>
                );
              })}
          </ul>
        ) : null}

        {run.phase !== "idle" ? (
          <div className="space-y-3 border-t border-border pt-4" aria-live="polite">
            <div className="flex items-center gap-2 text-sm font-medium">
              {run.phase === "running" ? (
                <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin text-info" />
              ) : run.phase === "complete" ? (
                <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-success" />
              ) : (
                <AlertTriangle aria-hidden="true" className="h-4 w-4 text-danger" />
              )}
              <span>{run.message || (run.phase === "running" ? "Action running" : "Action finished")}</span>
            </div>
            {run.percent !== null ? <MetricBar label="Action progress" value={run.percent} /> : null}
            {run.output.length ? (
              <div className="border border-border bg-background">
                <div className="flex items-center gap-2 border-b border-border px-3 py-2 font-mono text-[11px] text-muted-foreground">
                  <Terminal aria-hidden="true" className="h-3.5 w-3.5" />
                  Output
                </div>
                <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words p-3 font-mono text-xs">
                  {run.output.join("\n")}
                </pre>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {selected ? (
        <ModalOverlay onClose={() => setSelected(null)}>
          <div
            aria-labelledby={dialogTitleId}
            aria-modal="true"
            className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-lg border border-border bg-card"
            role="dialog"
          >
            <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-4 sm:px-5">
              <div className="min-w-0">
                <h2 className="font-mono text-base font-semibold" id={dialogTitleId}>
                  {selected.confirmation?.title ?? selected.label}
                </h2>
                {selected.description ? <p className="mt-1 text-sm text-muted-foreground">{selected.description}</p> : null}
              </div>
              <Button aria-label="Close action" className="h-9 w-9 shrink-0 px-0" onClick={() => setSelected(null)} size="sm" variant="ghost">
                <X aria-hidden="true" className="h-4 w-4" />
              </Button>
            </header>
            <div className="space-y-4 px-4 py-5 sm:px-5">
              {selected.parameters.map((parameter) => {
                const field = actionParameterAsField(
                  parameter,
                  actionParameterChoices(parameter, status),
                );
                return (
                  <SchemaField
                    error={fieldErrors[field.key]}
                    field={field}
                    idPrefix={`${catalog.provider_id}-${selected.id}`}
                    key={field.key}
                    onChange={(value) => {
                      setDraft((current) => ({ ...current, [field.key]: value }));
                      setFieldErrors((current) => ({ ...current, [field.key]: "" }));
                    }}
                    value={draft[field.key]}
                  />
                );
              })}
              {selected.confirmation ? (
                <div className={cn(
                  "flex items-start gap-2 border-l-2 px-3 py-2.5 text-sm",
                  selected.intent === "destructive"
                    ? "border-danger bg-danger/5 text-danger"
                    : "border-warning bg-warning/5 text-warning",
                )}>
                  <AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
                  {selected.confirmation.message}
                </div>
              ) : null}
              <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4">
                <Button onClick={() => setSelected(null)} variant="outline">Cancel</Button>
                <Button onClick={submitSelected} variant={actionVariant(selected.intent)}>
                  {selected.confirmation?.confirm_label ?? `Run ${selected.label}`}
                </Button>
              </div>
            </div>
          </div>
        </ModalOverlay>
      ) : null}
    </section>
  );
}
