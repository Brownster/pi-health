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

export interface CapabilityRegistryDiagnostic {
  code: string;
  message: string;
  provider_id?: string;
}

export interface ExtensionCapabilityDescriptor {
  id: string;
  provider_id: string;
  surface: string;
  operational: boolean;
  status: CapabilityStatus;
  [key: string]: unknown;
}

export interface ExtensionHealthSummary {
  state: CapabilityHealthState;
  message: string;
  counts: Partial<Record<CapabilityHealthState, number>>;
}

export interface ExtensionDescriptor {
  id: string;
  name: string;
  description: string;
  version: string;
  runtime_kind: string;
  source: string;
  installed: boolean;
  enabled: boolean;
  contract_state: "valid" | "invalid" | "incompatible";
  compatibility: "compatible" | "incompatible" | "unknown";
  health: ExtensionHealthSummary;
  capabilities: ExtensionCapabilityDescriptor[];
  update_state?: "available" | "current" | "unknown";
  [key: string]: unknown;
}

export interface ExtensionIndex {
  extensions: ExtensionDescriptor[];
  errors: CapabilityRegistryDiagnostic[];
}

export interface ExtensionDetails {
  extension: ExtensionDescriptor;
  errors: CapabilityRegistryDiagnostic[];
}

export type ExtensionLifecycleAction = "enable" | "disable" | "update" | "repair";

export interface ExtensionLifecycleResult {
  status: string;
  id?: string | null;
  enabled?: boolean;
  removed?: boolean;
  restart_required?: boolean;
}

export interface ExtensionInstallValues {
  type: "github";
  source: string;
  id?: string;
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
  return (await fetchExtensionIndex()).extensions;
}

export async function fetchExtension(id: string): Promise<ExtensionDescriptor> {
  return (await fetchExtensionDetails(id)).extension;
}

export async function fetchExtensionIndex(): Promise<ExtensionIndex> {
  const response = await requestApi<ExtensionIndex>("/api/extensions");
  return {
    extensions: Array.isArray(response.extensions) ? response.extensions : [],
    errors: Array.isArray(response.errors) ? response.errors : [],
  };
}

export async function fetchExtensionDetails(id: string): Promise<ExtensionDetails> {
  const response = await requestApi<ExtensionDetails>(
    `/api/extensions/${encodeURIComponent(id)}`,
  );
  return {
    extension: response.extension,
    errors: Array.isArray(response.errors) ? response.errors : [],
  };
}

export async function installExtension(
  values: ExtensionInstallValues,
): Promise<ExtensionLifecycleResult> {
  return requestApi<ExtensionLifecycleResult>("/api/extensions/install", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(values),
  });
}

export async function transitionExtension(
  id: string,
  action: ExtensionLifecycleAction,
): Promise<ExtensionLifecycleResult> {
  return requestApi<ExtensionLifecycleResult>(
    `/api/extensions/${encodeURIComponent(id)}/${action}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    },
  );
}

export async function removeExtension(id: string): Promise<ExtensionLifecycleResult> {
  return requestApi<ExtensionLifecycleResult>(
    `/api/extensions/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
}
