import type {
  CapabilityDescriptor,
  CapabilityHealthState,
  CapabilityStatus,
} from "./capabilities";
import type { PluginDetail, StoragePlugin } from "./storage-plugins";

export interface ProtectionProviderView {
  id: string;
  name: string;
  enabled: boolean;
  operational: boolean;
  status: CapabilityStatus;
  rendererId: string;
  rendererMode: "generic" | "tailored";
  source: "registry" | "legacy";
}

export interface ProtectionSetView {
  id: string;
  name: string;
  providerId: string;
  providerName: string;
  kind: string;
  health: CapabilityHealthState;
  protectedTargets: number | null;
  unprotectedTargets: number | null;
  parityTargets: number | null;
  lastRunAt: string | null;
  nextRunAt: string | null;
  schedule: string | null;
  requiredAction: string | null;
}

export interface ProtectionCapabilityView {
  enabledProviders: ProtectionProviderView[];
  availableProviders: ProtectionProviderView[];
  setupProviders: ProtectionProviderView[];
  configuredProviders: ProtectionProviderView[];
  protectionSets: ProtectionSetView[];
  summary: {
    totalSets: number;
    protectedTargets: number | null;
    unprotectedTargets: number | null;
    warnings: number;
    latestRunAt: string | null;
    nextRunAt: string | null;
  };
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function numberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function textOrNull(value: unknown): string | null {
  return value === null || value === undefined || value === "" ? null : String(value);
}

function stateFromLegacy(value: string, configured: boolean): CapabilityHealthState {
  if (!configured) return "unconfigured";
  if (["ok", "active", "healthy", "protected", "ready"].includes(value)) return "healthy";
  if (["warning", "degraded", "sync_required"].includes(value)) return "warning";
  if (["error", "failed"].includes(value)) return "error";
  if (value === "disabled") return "disabled";
  return "unknown";
}

function normalizeProvider(value: Record<string, unknown>): ProtectionProviderView | null {
  const status = record(value.status) as unknown as CapabilityStatus;
  if (
    !value.id ||
    status.schema_version !== "1" ||
    status.capability_id !== "storage.protection"
  ) {
    return null;
  }
  const renderer = record(value.renderer);
  return {
    id: String(value.id),
    name: String(value.name ?? value.id),
    enabled: Boolean(value.enabled ?? status.lifecycle.enabled),
    operational: Boolean(value.operational),
    status,
    rendererId: String(renderer.id ?? "generic"),
    rendererMode: renderer.mode === "tailored" ? "tailored" : "generic",
    source: value.source === "legacy" ? "legacy" : "registry",
  };
}

function protectionSetsForProvider(provider: ProtectionProviderView): ProtectionSetView[] {
  const rawSets = provider.status.details.protection_sets;
  if (!Array.isArray(rawSets)) return [];
  return rawSets.map((value, index) => {
    const item = record(value);
    const healthValue = String(item.health ?? provider.status.health.state);
    const health: CapabilityHealthState = [
      "healthy", "warning", "error", "unknown", "disabled", "unconfigured",
      "incompatible", "unavailable",
    ].includes(healthValue)
      ? (healthValue as CapabilityHealthState)
      : "unknown";
    const name = String(item.name ?? `protection-${index + 1}`);
    return {
      id: `${provider.id}:${name}`,
      name,
      providerId: provider.id,
      providerName: provider.name,
      kind: String(item.kind ?? item.type ?? "protection"),
      health,
      protectedTargets: numberOrNull(
        item.protected_targets ?? item.protected_disks ?? item.data_drives,
      ),
      unprotectedTargets: numberOrNull(
        item.unprotected_targets ?? item.unprotected_disks,
      ),
      parityTargets: numberOrNull(
        item.parity_targets ?? item.parity_drives ?? item.copies,
      ),
      lastRunAt: textOrNull(
        item.last_success_at ?? item.last_run_at ?? item.last_sync ?? item.last_check,
      ),
      nextRunAt: textOrNull(item.next_run_at ?? item.next_scheduled_at),
      schedule: textOrNull(item.schedule),
      requiredAction: item.sync_required === true
        ? "Sync required"
        : textOrNull(item.required_action),
    };
  });
}

function latestTimestamp(values: Array<string | null>): string | null {
  const valid = values.filter((value): value is string => value !== null && !Number.isNaN(Date.parse(value)));
  return valid.sort((left, right) => Date.parse(right) - Date.parse(left))[0] ?? null;
}

function earliestTimestamp(values: Array<string | null>): string | null {
  const valid = values.filter((value): value is string => value !== null && !Number.isNaN(Date.parse(value)));
  return valid.sort((left, right) => Date.parse(left) - Date.parse(right))[0] ?? null;
}

export function protectionCapabilityView(
  capability: CapabilityDescriptor,
): ProtectionCapabilityView {
  const providers = capability.providers
    .map((provider) => normalizeProvider(provider))
    .filter((provider): provider is ProtectionProviderView => provider !== null)
    .sort((left, right) => left.name.localeCompare(right.name));
  const enabledProviders = providers.filter((provider) => provider.enabled);
  const availableProviders = providers.filter((provider) => !provider.enabled);
  const setupProviders = enabledProviders.filter(
    (provider) => !provider.status.lifecycle.configured,
  );
  const configuredProviders = enabledProviders.filter(
    (provider) => provider.status.lifecycle.configured,
  );
  const protectionSets = configuredProviders
    .flatMap((provider) => protectionSetsForProvider(provider))
    .sort((left, right) => left.name.localeCompare(right.name));
  const protectedValues = protectionSets.map((item) => item.protectedTargets);
  const unprotectedValues = protectionSets.map((item) => item.unprotectedTargets);
  const providerWarnings = enabledProviders.filter((provider) =>
    ["warning", "error", "unavailable", "incompatible"].includes(provider.status.health.state),
  ).length;
  const setWarnings = protectionSets.filter((item) =>
    item.requiredAction !== null || ["warning", "error", "unavailable"].includes(item.health),
  ).length;
  return {
    enabledProviders,
    availableProviders,
    setupProviders,
    configuredProviders,
    protectionSets,
    summary: {
      totalSets: protectionSets.length,
      protectedTargets: protectedValues.length && protectedValues.every((value) => value !== null)
        ? protectedValues.reduce<number>((total, value) => total + (value ?? 0), 0)
        : null,
      unprotectedTargets: unprotectedValues.length && unprotectedValues.every((value) => value !== null)
        ? unprotectedValues.reduce<number>((total, value) => total + (value ?? 0), 0)
        : null,
      warnings: Math.max(providerWarnings, setWarnings),
      latestRunAt: latestTimestamp(protectionSets.map((item) => item.lastRunAt)),
      nextRunAt: earliestTimestamp(protectionSets.map((item) => item.nextRunAt)),
    },
  };
}

export function adaptLegacyProtectionProviders(
  plugins: StoragePlugin[],
  details: Record<string, PluginDetail | null>,
  observedAt: string,
): CapabilityDescriptor {
  const snapraid = plugins.find((plugin) => plugin.id === "snapraid" && plugin.installed);
  if (!snapraid) return { id: "storage.protection", surface: "protection", providers: [] };

  const detail = details.snapraid;
  const rawStatus = record(detail?.status);
  const statusDetails = record(rawStatus.details);
  const drives = Array.isArray(detail?.config.drives)
    ? (detail.config.drives as Record<string, unknown>[])
    : [];
  const dataDrives = numberOrNull(statusDetails.data_drives)
    ?? drives.filter((drive) => drive.role === "data").length;
  const parityDrives = numberOrNull(statusDetails.parity_drives)
    ?? drives.filter((drive) => drive.role === "parity").length;
  const schedule = record(detail?.config.schedule);
  const scheduleLabel = schedule.sync_enabled === true
    ? String(schedule.sync_cron ?? "Scheduled sync")
    : schedule.scrub_enabled === true
      ? String(schedule.scrub_cron ?? "Scheduled scrub")
      : null;
  const healthState = snapraid.enabled
    ? stateFromLegacy(String(rawStatus.status ?? snapraid.status), snapraid.configured)
    : "disabled";
  const protectionSets = snapraid.configured && detail ? [{
    name: "SnapRAID parity",
    kind: "parity",
    health: healthState,
    protected_targets: dataDrives,
    unprotected_targets: null,
    parity_targets: parityDrives,
    last_run_at: textOrNull(statusDetails.last_run_at),
    next_run_at: null,
    schedule: scheduleLabel,
    sync_required: statusDetails.sync_required === true,
    required_action: healthState === "error"
      ? String(rawStatus.message ?? "Review provider error")
      : null,
  }] : [];
  const status: CapabilityStatus = {
    schema_version: "1",
    provider_id: snapraid.id,
    capability_id: "storage.protection",
    observed_at: observedAt,
    lifecycle: {
      installed: snapraid.installed,
      enabled: snapraid.enabled,
      configured: snapraid.configured,
      compatibility: "compatible",
      availability: detail ? "available" : "unknown",
    },
    health: {
      state: healthState,
      message: String(rawStatus.message ?? snapraid.status_message ?? "Protection status is available through the compatibility adapter."),
      issues: [],
    },
    summary: [],
    metrics: [],
    recent_activity: [],
    details: { ...statusDetails, protection_sets: protectionSets },
  };
  return {
    id: "storage.protection",
    surface: "protection",
    providers: [{
      id: snapraid.id,
      name: snapraid.name,
      enabled: snapraid.enabled,
      operational: snapraid.enabled && snapraid.configured && healthState === "healthy",
      renderer: { id: "snapraid", mode: "tailored" },
      status,
      source: "legacy",
    }],
  };
}

export function enrichProtectionCapability(
  capability: CapabilityDescriptor,
  legacy: CapabilityDescriptor,
): CapabilityDescriptor {
  if (!capability.providers.length) return legacy;
  const legacyById = new Map(legacy.providers.map((provider) => [provider.id, provider]));
  return {
    ...capability,
    providers: capability.providers.map((provider) => {
      const legacyProvider = legacyById.get(provider.id);
      if (!legacyProvider) return provider;
      const status = record(provider.status) as unknown as CapabilityStatus;
      const legacyStatus = record(legacyProvider.status) as unknown as CapabilityStatus;
      return Array.isArray(status.details?.protection_sets)
        ? provider
        : { ...provider, status: { ...status, details: legacyStatus.details } };
    }),
  };
}
