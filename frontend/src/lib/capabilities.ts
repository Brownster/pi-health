import { requestApi } from "@/lib/api";

export type CapabilityScalar = string | number | boolean | null;
export type CapabilityTone = "neutral" | "success" | "warning" | "danger";

export interface CapabilityChoice {
  value: Exclude<CapabilityScalar, null>;
  label: string;
}

export interface CapabilitySetupField {
  key: string;
  label: string;
  description?: string;
  type: "text" | "integer" | "number" | "boolean" | "select" | "path" | "secret_reference";
  required: boolean;
  read_only?: boolean;
  default?: CapabilityScalar;
  placeholder?: string;
  minimum?: number;
  maximum?: number;
  min_length?: number;
  max_length?: number;
  pattern?: string;
  choices?: CapabilityChoice[];
}

export interface CapabilitySetupSection {
  id: string;
  label: string;
  description?: string;
  fields: string[];
}

export interface CapabilitySetupSchema {
  schema_version: "1";
  schema_id: string;
  title: string;
  description?: string;
  fields: CapabilitySetupField[];
  sections?: CapabilitySetupSection[];
}

export interface CapabilityFieldError {
  field: string;
  code: string;
  message: string;
}

export interface CapabilitySetupValidation {
  schema_version: "1";
  valid: boolean;
  errors: CapabilityFieldError[];
}

export type CapabilityHealthState =
  | "healthy"
  | "warning"
  | "error"
  | "unknown"
  | "disabled"
  | "unconfigured"
  | "incompatible"
  | "unavailable";

export interface CapabilityStatus {
  schema_version: "1";
  provider_id: string;
  capability_id: string;
  observed_at: string;
  lifecycle: {
    installed: boolean;
    enabled: boolean;
    configured: boolean;
    compatibility: "compatible" | "incompatible" | "unknown";
    availability: "available" | "unavailable" | "unknown";
  };
  health: {
    state: CapabilityHealthState;
    message: string;
    issues: Array<{
      code: string;
      severity: "info" | "warning" | "error";
      message: string;
      recovery?: string;
    }>;
  };
  summary: Array<{
    id: string;
    label: string;
    value: CapabilityScalar;
    unit?: string;
    tone: CapabilityTone;
  }>;
  metrics: Array<{
    id: string;
    label: string;
    value: number;
    unit?: string;
    minimum?: number;
    maximum?: number;
  }>;
  recent_activity: Array<{
    id: string;
    occurred_at: string;
    kind: "info" | "success" | "warning" | "error";
    summary: string;
  }>;
  details: Record<string, unknown>;
}

export interface CapabilityActionParameter {
  name: string;
  label: string;
  description?: string;
  type: "text" | "integer" | "number" | "boolean" | "select" | "path";
  required: boolean;
  default?: CapabilityScalar;
  minimum?: number;
  maximum?: number;
  pattern?: string;
  choices?: CapabilityChoice[];
  source?: string;
}

export interface CapabilityAction {
  id: string;
  label: string;
  description?: string;
  intent: "read" | "diagnostic" | "mutation" | "destructive";
  permission: "capability.view" | "capability.diagnose" | "capability.operate" | "extensions.admin";
  timeout_seconds: number;
  parameters: CapabilityActionParameter[];
  confirmation?: {
    title: string;
    message: string;
    confirm_label: string;
  };
  result_mode: "immediate" | "stream";
}

export interface CapabilityActionCatalog {
  schema_version: "1";
  provider_id: string;
  capability_id: string;
  actions: CapabilityAction[];
  availability: Array<{
    id: string;
    available: boolean;
    unavailable_reason?: string;
  }>;
}

export interface CapabilityActionEvent {
  schema_version: "1";
  operation_id: string;
  sequence: number;
  type: "output" | "progress" | "complete" | "error";
  message?: string;
  percent?: number;
  success?: boolean;
  code?: string;
  result?: unknown;
}

export interface CapabilityDescriptor {
  id: string;
  surface: string;
  providers: Array<Record<string, unknown> & { id: string }>;
  [key: string]: unknown;
}

export interface ExtensionDescriptor {
  id: string;
  name: string;
  [key: string]: unknown;
}

export async function fetchCapabilities(): Promise<CapabilityDescriptor[]> {
  const response = await requestApi<{ capabilities: CapabilityDescriptor[] }>(
    "/api/capabilities",
  );
  return response.capabilities ?? [];
}

export async function fetchCapability(id: string): Promise<CapabilityDescriptor> {
  const response = await requestApi<{ capability: CapabilityDescriptor }>(
    `/api/capabilities/${encodeURIComponent(id)}`,
  );
  return response.capability;
}

export async function fetchExtensions(): Promise<ExtensionDescriptor[]> {
  const response = await requestApi<{ extensions: ExtensionDescriptor[] }>(
    "/api/extensions",
  );
  return response.extensions ?? [];
}

export async function fetchExtension(id: string): Promise<ExtensionDescriptor> {
  const response = await requestApi<{ extension: ExtensionDescriptor }>(
    `/api/extensions/${encodeURIComponent(id)}`,
  );
  return response.extension;
}
