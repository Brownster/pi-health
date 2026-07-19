import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Loader2, Save, TriangleAlert } from "lucide-react";

import { SchemaField } from "@/components/capabilities/schema-field";
import { Button } from "@/components/ui/button";
import type {
  CapabilityFieldError,
  CapabilitySetupSchema,
  CapabilitySetupValidation,
} from "@/lib/capabilities";
import {
  groupSetupFields,
  setupInitialValues,
  type CapabilityFormValues,
  validateSetupValues,
} from "@/lib/capability-renderer";

function errorMap(errors: CapabilityFieldError[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const error of errors) {
    if (!result[error.field]) result[error.field] = error.message;
  }
  return result;
}

function publicErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : "Configuration could not be saved.";
  return message.replace(/\s+/g, " ").trim().slice(0, 240) || "Configuration could not be saved.";
}

export function GenericSetupForm({
  schema,
  initialValues = {},
  errors = [],
  disabled = false,
  onSubmit,
}: {
  schema: CapabilitySetupSchema;
  initialValues?: CapabilityFormValues;
  errors?: CapabilityFieldError[];
  disabled?: boolean;
  onSubmit: (
    values: CapabilityFormValues,
  ) => Promise<CapabilitySetupValidation | void>;
}) {
  const [draft, setDraft] = useState(() => setupInitialValues(schema, initialValues));
  const [localErrors, setLocalErrors] = useState<CapabilityFieldError[]>([]);
  const [remoteErrors, setRemoteErrors] = useState(errors);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const initialValuesSignature = JSON.stringify(initialValues);
  const errorsSignature = JSON.stringify(errors);

  useEffect(() => {
    setDraft(setupInitialValues(schema, initialValues));
    setLocalErrors([]);
    setRemoteErrors(errors);
    setNotice(null);
  }, [schema.schema_id, initialValuesSignature, errorsSignature]);

  const groups = useMemo(() => groupSetupFields(schema), [schema]);
  const messages = errorMap([...remoteErrors, ...localErrors]);
  const editable = schema.fields.some((field) => !field.read_only);

  async function submit() {
    const validation = validateSetupValues(schema.fields, draft);
    setLocalErrors(validation.errors);
    setRemoteErrors([]);
    setNotice(null);
    if (validation.errors.length) {
      requestAnimationFrame(() => {
        const first = validation.errors[0];
        const id = `${schema.schema_id}-field-${first.field.split(".").join("-")}`;
        document.getElementById(id)?.focus();
      });
      return;
    }

    setBusy(true);
    try {
      const result = await onSubmit(validation.values);
      if (result && !result.valid) {
        setRemoteErrors(result.errors);
        requestAnimationFrame(() => {
          const first = result.errors.find((item) => item.field !== "_form");
          if (!first) return;
          const id = `${schema.schema_id}-field-${first.field.split(".").join("-")}`;
          document.getElementById(id)?.focus();
        });
      } else {
        setNotice("Configuration saved.");
      }
    } catch (error) {
      setRemoteErrors([
        {
          field: "_form",
          code: "save_failed",
          message: publicErrorMessage(error),
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby={`${schema.schema_id}-title`} className="rounded-lg border border-border bg-card">
      <header className="border-b border-border px-4 py-4 sm:px-5">
        <h2 className="font-mono text-sm font-semibold" id={`${schema.schema_id}-title`}>
          {schema.title}
        </h2>
        {schema.description ? (
          <p className="mt-1 text-sm text-muted-foreground">{schema.description}</p>
        ) : null}
      </header>

      <form
        className="space-y-5 px-4 py-5 sm:px-5"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        {messages._form ? (
          <div className="flex items-start gap-2 border-l-2 border-danger bg-danger/5 px-3 py-2 text-sm text-danger" role="alert">
            <TriangleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
            {messages._form}
          </div>
        ) : null}

        {groups.map((group, index) => (
          <fieldset className={index ? "border-t border-border pt-5" : ""} key={group.id}>
            <legend className="font-mono text-xs font-semibold uppercase text-muted-foreground">
              {group.label}
            </legend>
            {group.description ? (
              <p className="mt-1 text-xs text-muted-foreground">{group.description}</p>
            ) : null}
            <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2">
              {group.fields.map((field) => (
                <SchemaField
                  error={messages[field.key]}
                  field={field}
                  idPrefix={schema.schema_id}
                  key={field.key}
                  onChange={(value) => {
                    setDraft((current) => ({ ...current, [field.key]: value }));
                    setLocalErrors((current) => current.filter((item) => item.field !== field.key));
                    setRemoteErrors((current) => current.filter((item) => item.field !== field.key));
                    setNotice(null);
                  }}
                  value={draft[field.key]}
                />
              ))}
            </div>
          </fieldset>
        ))}

        <div className="flex min-h-11 flex-wrap items-center gap-3 border-t border-border pt-4">
          <Button className="gap-2" disabled={disabled || busy || !editable} type="submit">
            {busy ? (
              <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
            ) : (
              <Save aria-hidden="true" className="h-4 w-4" />
            )}
            Save configuration
          </Button>
          {notice ? (
            <span className="flex items-center gap-1.5 text-sm text-success" role="status">
              <CheckCircle2 aria-hidden="true" className="h-4 w-4" />
              {notice}
            </span>
          ) : null}
        </div>
      </form>
    </section>
  );
}
