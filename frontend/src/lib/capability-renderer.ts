import type {
  CapabilityActionEvent,
  CapabilityActionParameter,
  CapabilityChoice,
  CapabilityFieldError,
  CapabilityScalar,
  CapabilitySetupField,
  CapabilitySetupSchema,
  CapabilityStatus,
} from "./capabilities";

export type CapabilityFormValues = Record<string, CapabilityScalar>;

export interface CapabilitySetupGroup {
  id: string;
  label: string;
  description?: string;
  fields: CapabilitySetupField[];
}

export interface CapabilityFormResult {
  values: CapabilityFormValues;
  errors: CapabilityFieldError[];
}

export interface CapabilityActionRunState {
  phase: "idle" | "running" | "complete" | "error";
  operationId: string | null;
  lastSequence: number;
  percent: number | null;
  output: string[];
  message: string;
  success: boolean | null;
}

const MAX_ACTION_OUTPUT_LINES = 200;
const MAX_ACTION_OUTPUT_BYTES = 64 * 1024;
const FORBIDDEN_PATH_PARTS = new Set(["__proto__", "prototype", "constructor"]);

function isEmpty(value: CapabilityScalar | undefined): boolean {
  return value === undefined || value === null || value === "";
}

function scalarEquals(left: CapabilityScalar, right: CapabilityScalar): boolean {
  return typeof left === typeof right && left === right;
}

export function setupInitialValues(
  schema: CapabilitySetupSchema,
  supplied: CapabilityFormValues = {},
): CapabilityFormValues {
  const values: CapabilityFormValues = {};
  for (const field of schema.fields) {
    if (Object.prototype.hasOwnProperty.call(supplied, field.key)) {
      values[field.key] = supplied[field.key];
    } else if (field.default !== undefined) {
      values[field.key] = field.default;
    } else {
      values[field.key] = field.type === "boolean" ? false : "";
    }
  }
  return values;
}

export function groupSetupFields(schema: CapabilitySetupSchema): CapabilitySetupGroup[] {
  const fields = new Map(schema.fields.map((field) => [field.key, field]));
  const grouped = new Set<string>();
  const groups: CapabilitySetupGroup[] = (schema.sections ?? []).map((section) => ({
    id: section.id,
    label: section.label,
    description: section.description,
    fields: section.fields.flatMap((key) => {
      const field = fields.get(key);
      if (!field || grouped.has(key)) return [];
      grouped.add(key);
      return [field];
    }),
  }));
  const remaining = schema.fields.filter((field) => !grouped.has(field.key));
  if (remaining.length) {
    groups.push({
      id: "configuration",
      label: "Configuration",
      fields: remaining,
    });
  }
  return groups.filter((group) => group.fields.length > 0);
}

export function validateSetupValues(
  fields: CapabilitySetupField[],
  draft: CapabilityFormValues,
): CapabilityFormResult {
  const values: CapabilityFormValues = {};
  const errors: CapabilityFieldError[] = [];

  for (const field of fields) {
    const raw = draft[field.key];
    if (isEmpty(raw)) {
      if (field.required) {
        errors.push({
          field: field.key,
          code: "required",
          message: `${field.label} is required.`,
        });
      }
      continue;
    }

    let value = raw;
    if (field.type === "integer" || field.type === "number") {
      const numeric = typeof raw === "number" ? raw : Number(raw);
      if (!Number.isFinite(numeric) || (field.type === "integer" && !Number.isInteger(numeric))) {
        errors.push({
          field: field.key,
          code: field.type === "integer" ? "invalid_integer" : "invalid_number",
          message: `${field.label} must be a valid ${field.type}.`,
        });
        continue;
      }
      if (field.minimum !== undefined && numeric < field.minimum) {
        errors.push({
          field: field.key,
          code: "below_minimum",
          message: `${field.label} must be at least ${field.minimum}.`,
        });
      }
      if (field.maximum !== undefined && numeric > field.maximum) {
        errors.push({
          field: field.key,
          code: "above_maximum",
          message: `${field.label} must be no more than ${field.maximum}.`,
        });
      }
      value = numeric;
    }

    if (typeof value === "string") {
      if (field.min_length !== undefined && value.length < field.min_length) {
        errors.push({
          field: field.key,
          code: "below_min_length",
          message: `${field.label} is too short.`,
        });
      }
      if (field.max_length !== undefined && value.length > field.max_length) {
        errors.push({
          field: field.key,
          code: "above_max_length",
          message: `${field.label} is too long.`,
        });
      }
    }

    if (
      field.type === "select" &&
      field.choices &&
      !field.choices.some((choice) => scalarEquals(choice.value, value))
    ) {
      errors.push({
        field: field.key,
        code: "invalid_choice",
        message: `${field.label} has an invalid selection.`,
      });
    }
    values[field.key] = value;
  }
  return { values, errors };
}

export function actionParameterAsField(
  parameter: CapabilityActionParameter,
  choices?: CapabilityChoice[],
): CapabilitySetupField {
  return {
    key: parameter.name,
    label: parameter.label,
    description: parameter.description,
    type: parameter.type,
    required: parameter.required,
    default: parameter.default,
    minimum: parameter.minimum,
    maximum: parameter.maximum,
    choices: choices ?? parameter.choices,
  };
}

export function serializeChoice(value: Exclude<CapabilityScalar, null>): string {
  return JSON.stringify({ type: typeof value, value });
}

export function deserializeChoice(
  token: string,
  choices: CapabilityChoice[],
): Exclude<CapabilityScalar, null> | "" {
  return choices.find((choice) => serializeChoice(choice.value) === token)?.value ?? "";
}

function traverseStatusSource(source: string, status: CapabilityStatus): unknown {
  if (!source.startsWith("status.")) return undefined;
  const parts = source.slice(7).split(".");
  if (parts.some((part) => FORBIDDEN_PATH_PARTS.has(part.replace(/\[\]$/, "")))) {
    return undefined;
  }
  let current: unknown = status;
  for (const rawPart of parts) {
    const arrayPart = rawPart.endsWith("[]");
    const part = arrayPart ? rawPart.slice(0, -2) : rawPart;
    if (part === "summary" && current === status) {
      current = status.summary;
    } else if (part === "details" && current === status) {
      current = status.details;
    } else if (Array.isArray(current)) {
      const summaryItem = current.find(
        (item) => typeof item === "object" && item !== null && "id" in item && item.id === part,
      );
      if (summaryItem) {
        current = "value" in summaryItem ? summaryItem.value : summaryItem;
      } else {
        current = current.flatMap((item) => {
          if (typeof item !== "object" || item === null) return [];
          const value = (item as Record<string, unknown>)[part];
          return value === undefined ? [] : [value];
        });
      }
    } else if (typeof current === "object" && current !== null) {
      current = (current as Record<string, unknown>)[part];
    } else {
      return undefined;
    }
    if (arrayPart && !Array.isArray(current)) return undefined;
  }
  return current;
}

export function actionParameterChoices(
  parameter: CapabilityActionParameter,
  status: CapabilityStatus,
): CapabilityChoice[] {
  if (parameter.choices) return parameter.choices;
  if (!parameter.source) return [];
  const source = traverseStatusSource(parameter.source, status);
  const items = Array.isArray(source) ? source : [source];
  return items.slice(0, 128).flatMap((item): CapabilityChoice[] => {
    if (["string", "number", "boolean"].includes(typeof item)) {
      return [{ value: item as Exclude<CapabilityScalar, null>, label: String(item) }];
    }
    if (typeof item !== "object" || item === null) return [];
    const record = item as Record<string, unknown>;
    const value = record.value ?? record.id ?? record.name;
    const label = record.label ?? record.name ?? value;
    if (!["string", "number", "boolean"].includes(typeof value) || typeof label !== "string") {
      return [];
    }
    return [{ value: value as Exclude<CapabilityScalar, null>, label }];
  });
}

export function metricPercent(value: number, minimum = 0, maximum = 100): number | null {
  if (![value, minimum, maximum].every(Number.isFinite) || maximum <= minimum) return null;
  return Math.min(100, Math.max(0, ((value - minimum) / (maximum - minimum)) * 100));
}

export function initialActionRunState(): CapabilityActionRunState {
  return {
    phase: "idle",
    operationId: null,
    lastSequence: -1,
    percent: null,
    output: [],
    message: "",
    success: null,
  };
}

function boundedOutput(lines: string[]): string[] {
  const kept = lines.slice(-MAX_ACTION_OUTPUT_LINES);
  const encoder = new TextEncoder();
  let bytes = kept.reduce((total, line) => total + encoder.encode(line).byteLength, 0);
  while (kept.length > 1 && bytes > MAX_ACTION_OUTPUT_BYTES) {
    bytes -= encoder.encode(kept.shift() ?? "").byteLength;
  }
  return kept;
}

export function reduceActionEvent(
  state: CapabilityActionRunState,
  event: CapabilityActionEvent,
): CapabilityActionRunState {
  if (state.operationId && event.operation_id !== state.operationId) return state;
  if (event.sequence <= state.lastSequence) return state;
  const next: CapabilityActionRunState = {
    ...state,
    phase: "running",
    operationId: state.operationId ?? event.operation_id,
    lastSequence: event.sequence,
  };
  if (event.type === "output" && event.message) {
    next.output = boundedOutput([...state.output, event.message.slice(0, 2_000)]);
  } else if (event.type === "progress") {
    next.percent = Number.isFinite(event.percent)
      ? Math.min(100, Math.max(0, Number(event.percent)))
      : state.percent;
    next.message = event.message?.slice(0, 240) ?? state.message;
  } else if (event.type === "complete") {
    next.phase = event.success === false ? "error" : "complete";
    next.success = event.success !== false;
    next.percent = event.success === false ? state.percent : 100;
    next.message = event.message?.slice(0, 240) ?? "Action completed.";
  } else if (event.type === "error") {
    next.phase = "error";
    next.success = false;
    next.message = event.message?.slice(0, 240) ?? "Action failed.";
  }
  return next;
}
