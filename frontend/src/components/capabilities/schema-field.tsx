import { KeyRound } from "lucide-react";

import type { CapabilityScalar, CapabilitySetupField } from "@/lib/capabilities";
import { deserializeChoice, serializeChoice } from "@/lib/capability-renderer";
import { cn } from "@/lib/utils";

const inputClass =
  "min-h-11 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60";

export function SchemaField({
  field,
  value,
  error,
  idPrefix = "capability",
  onChange,
}: {
  field: CapabilitySetupField;
  value: CapabilityScalar | undefined;
  error?: string;
  idPrefix?: string;
  onChange: (value: CapabilityScalar) => void;
}) {
  const inputId = `${idPrefix}-field-${field.key.split(".").join("-")}`;
  const describedBy = [field.description ? `${inputId}-description` : "", error ? `${inputId}-error` : ""]
    .filter(Boolean)
    .join(" ") || undefined;

  if (field.type === "boolean") {
    return (
      <label className="flex min-h-11 cursor-pointer items-start gap-3 rounded-md border border-border px-3 py-2.5">
        <input
          checked={value === true}
          className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
          disabled={field.read_only}
          name={field.key}
          onChange={(event) => onChange(event.target.checked)}
          type="checkbox"
        />
        <span className="min-w-0">
          <span className="block text-sm font-medium">{field.label}</span>
          {field.description ? (
            <span className="mt-0.5 block text-xs text-muted-foreground">{field.description}</span>
          ) : null}
          {error ? <span className="mt-1 block text-xs text-danger">{error}</span> : null}
        </span>
      </label>
    );
  }

  return (
    <label className="block space-y-1.5" htmlFor={inputId}>
      <span className="flex items-center gap-1.5 text-sm font-medium">
        {field.type === "secret_reference" ? (
          <KeyRound aria-hidden="true" className="h-3.5 w-3.5 text-muted-foreground" />
        ) : null}
        {field.label}
        {field.required ? <span className="text-danger" aria-hidden="true">*</span> : null}
      </span>
      {field.description ? (
        <span className="block text-xs text-muted-foreground" id={`${inputId}-description`}>
          {field.description}
        </span>
      ) : null}
      {field.type === "select" ? (
        <select
          aria-describedby={describedBy}
          aria-invalid={Boolean(error)}
          className={cn(inputClass, error && "border-danger/60")}
          disabled={field.read_only}
          id={inputId}
          name={field.key}
          onChange={(event) =>
            onChange(deserializeChoice(event.target.value, field.choices ?? []))
          }
          value={value === "" || value == null ? "" : serializeChoice(value)}
        >
          <option disabled={field.required} value="">
            {field.required ? "Select an option" : "Not set"}
          </option>
          {(field.choices ?? []).map((choice) => (
            <option key={serializeChoice(choice.value)} value={serializeChoice(choice.value)}>
              {choice.label}
            </option>
          ))}
        </select>
      ) : (
        <input
          aria-describedby={describedBy}
          aria-invalid={Boolean(error)}
          autoComplete={field.type === "secret_reference" ? "off" : undefined}
          className={cn(inputClass, error && "border-danger/60")}
          disabled={field.read_only}
          id={inputId}
          inputMode={field.type === "integer" || field.type === "number" ? "decimal" : undefined}
          max={field.maximum}
          maxLength={field.max_length}
          min={field.minimum}
          minLength={field.min_length}
          name={field.key}
          onChange={(event) => onChange(event.target.value)}
          placeholder={field.placeholder}
          spellCheck={field.type === "text" ? undefined : false}
          type={field.type === "integer" || field.type === "number" ? "number" : "text"}
          value={value == null ? "" : String(value)}
        />
      )}
      {error ? (
        <span className="block text-xs text-danger" id={`${inputId}-error`} role="alert">
          {error}
        </span>
      ) : null}
    </label>
  );
}
