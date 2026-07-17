import { CapabilityActions, type CapabilityActionExecutor } from "@/components/capabilities/capability-actions";
import { CapabilityStatusPanel } from "@/components/capabilities/capability-status-panel";
import { GenericSetupForm } from "@/components/capabilities/generic-setup-form";
import type {
  CapabilityActionCatalog,
  CapabilityFieldError,
  CapabilitySetupSchema,
  CapabilitySetupValidation,
  CapabilityStatus,
} from "@/lib/capabilities";
import type { CapabilityFormValues } from "@/lib/capability-renderer";

export function GenericCapabilityRenderer({
  status,
  setup,
  setupValues,
  setupErrors,
  actions,
  onSave,
  onAction,
}: {
  status: CapabilityStatus;
  setup?: CapabilitySetupSchema;
  setupValues?: CapabilityFormValues;
  setupErrors?: CapabilityFieldError[];
  actions?: CapabilityActionCatalog;
  onSave?: (
    values: CapabilityFormValues,
  ) => Promise<CapabilitySetupValidation | void>;
  onAction?: CapabilityActionExecutor;
}) {
  return (
    <div className="space-y-5" data-capability-renderer="generic">
      <CapabilityStatusPanel status={status} />
      {setup && onSave ? (
        <GenericSetupForm
          disabled={!status.lifecycle.enabled || status.lifecycle.compatibility !== "compatible"}
          errors={setupErrors}
          initialValues={setupValues}
          onSubmit={onSave}
          schema={setup}
        />
      ) : null}
      {actions && onAction ? (
        <CapabilityActions catalog={actions} execute={onAction} status={status} />
      ) : null}
    </div>
  );
}
