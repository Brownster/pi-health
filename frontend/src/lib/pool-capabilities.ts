import type {
  CapabilityDescriptor,
  CapabilityHealthState,
  CapabilityStatus,
} from "./capabilities";
import type { PluginDetail, StoragePlugin } from "./storage-plugins";

export interface PoolProviderView {
  id: string;
  name: string;
  enabled: boolean;
  operational: boolean;
  status: CapabilityStatus;
  rendererId: string;
  rendererMode: "generic" | "tailored";
  source: "registry" | "legacy";
}

export interface PoolView {
  id: string;
  name: string;
  providerId: string;
  providerName: string;
  mountPoint: string | null;
  mounted: boolean;
  branchCount: number | null;
  policy: string | null;
  totalBytes: number | null;
  freeBytes: number | null;
  usedPercent: number | null;
  health: CapabilityHealthState;
  recentAction: string | null;
}

export interface PoolCapabilityView {
  enabledProviders: PoolProviderView[];
  availableProviders: PoolProviderView[];
  setupProviders: PoolProviderView[];
  configuredProviders: PoolProviderView[];
  pools: PoolView[];
  summary: {
    totalPools: number;
    mountedPools: number;
    totalBytes: number | null;
    freeBytes: number | null;
    warnings: number;
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

function stateFromLegacy(value: string, configured: boolean): CapabilityHealthState {
  if (!configured) return "unconfigured";
  if (["ok", "active", "healthy", "mounted", "ready"].includes(value)) return "healthy";
  if (["warning", "degraded", "unmounted"].includes(value)) return "warning";
  if (["error", "failed"].includes(value)) return "error";
  if (value === "disabled") return "disabled";
  return "unknown";
}

function normalizeProvider(value: Record<string, unknown>): PoolProviderView | null {
  const status = record(value.status) as unknown as CapabilityStatus;
  if (
    !value.id ||
    status.schema_version !== "1" ||
    status.capability_id !== "storage.pooling"
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

function poolsForProvider(provider: PoolProviderView): PoolView[] {
  const rawPools = provider.status.details.pools;
  if (!Array.isArray(rawPools)) return [];
  return rawPools.map((value, index) => {
    const pool = record(value);
    const branches = pool.branches;
    const branchCount = Array.isArray(branches)
      ? branches.length
      : numberOrNull(branches ?? pool.branch_count);
    const totalBytes = numberOrNull(pool.total_bytes);
    const freeBytes = numberOrNull(pool.free_bytes ?? pool.available_bytes);
    const explicitPercent = numberOrNull(pool.used_percent);
    const usedPercent = explicitPercent ?? (
      totalBytes !== null && totalBytes > 0 && freeBytes !== null
        ? ((totalBytes - freeBytes) / totalBytes) * 100
        : null
    );
    const mounted = Boolean(pool.mounted);
    const healthValue = String(pool.health ?? "");
    const health: CapabilityHealthState = [
      "healthy", "warning", "error", "unknown", "disabled", "unconfigured", "incompatible", "unavailable",
    ].includes(healthValue)
      ? (healthValue as CapabilityHealthState)
      : mounted
        ? "healthy"
        : "warning";
    const name = String(pool.name ?? `pool-${index + 1}`);
    return {
      id: `${provider.id}:${name}`,
      name,
      providerId: provider.id,
      providerName: provider.name,
      mountPoint: pool.mount_point != null ? String(pool.mount_point) : null,
      mounted,
      branchCount,
      policy: pool.policy != null
        ? String(pool.policy)
        : pool.create_policy != null
          ? String(pool.create_policy)
          : null,
      totalBytes,
      freeBytes,
      usedPercent,
      health,
      recentAction: pool.recent_action != null ? String(pool.recent_action) : null,
    };
  });
}

export function poolCapabilityView(capability: CapabilityDescriptor): PoolCapabilityView {
  const providers = capability.providers
    .map((provider) => normalizeProvider(provider))
    .filter((provider): provider is PoolProviderView => provider !== null)
    .sort((left, right) => left.name.localeCompare(right.name));
  const enabledProviders = providers.filter((provider) => provider.enabled);
  const availableProviders = providers.filter((provider) => !provider.enabled);
  const setupProviders = enabledProviders.filter(
    (provider) => !provider.status.lifecycle.configured,
  );
  const configuredProviders = enabledProviders.filter(
    (provider) => provider.status.lifecycle.configured,
  );
  const pools = configuredProviders
    .flatMap((provider) => poolsForProvider(provider))
    .sort((left, right) => left.name.localeCompare(right.name));
  const withCapacity = pools.filter((pool) => pool.totalBytes !== null);
  const withFreeSpace = pools.filter((pool) => pool.freeBytes !== null);
  const attentionProviders = enabledProviders.filter((provider) =>
    ["warning", "error", "unavailable", "incompatible"].includes(provider.status.health.state),
  ).length;
  const unavailablePools = pools.filter((pool) => !pool.mounted).length;
  return {
    enabledProviders,
    availableProviders,
    setupProviders,
    configuredProviders,
    pools,
    summary: {
      totalPools: pools.length,
      mountedPools: pools.filter((pool) => pool.mounted).length,
      totalBytes: withCapacity.length
        ? withCapacity.reduce((total, pool) => total + (pool.totalBytes ?? 0), 0)
        : null,
      freeBytes: withFreeSpace.length
        ? withFreeSpace.reduce((total, pool) => total + (pool.freeBytes ?? 0), 0)
        : null,
      warnings: Math.max(attentionProviders, unavailablePools),
    },
  };
}

export function adaptLegacyPoolingProviders(
  plugins: StoragePlugin[],
  details: Record<string, PluginDetail | null>,
  observedAt: string,
): CapabilityDescriptor {
  const mergerfs = plugins.find((plugin) => plugin.id === "mergerfs" && plugin.installed);
  if (!mergerfs) {
    return { id: "storage.pooling", surface: "pools", providers: [] };
  }
  const detail = details.mergerfs;
  const rawStatus = record(detail?.status);
  const statusDetails = record(rawStatus.details);
  const healthState = mergerfs.enabled
    ? stateFromLegacy(String(rawStatus.status ?? mergerfs.status), mergerfs.configured)
    : "disabled";
  const status: CapabilityStatus = {
    schema_version: "1",
    provider_id: mergerfs.id,
    capability_id: "storage.pooling",
    observed_at: observedAt,
    lifecycle: {
      installed: mergerfs.installed,
      enabled: mergerfs.enabled,
      configured: mergerfs.configured,
      compatibility: "compatible",
      availability: detail ? "available" : "unknown",
    },
    health: {
      state: healthState,
      message: String(rawStatus.message ?? mergerfs.status_message ?? "Provider status is available through the compatibility adapter."),
      issues: [],
    },
    summary: [],
    metrics: [],
    recent_activity: [],
    details: statusDetails,
  };
  return {
    id: "storage.pooling",
    surface: "pools",
    providers: [{
      id: mergerfs.id,
      name: mergerfs.name,
      enabled: mergerfs.enabled,
      operational: mergerfs.enabled && mergerfs.configured && healthState === "healthy",
      renderer: { id: "mergerfs", mode: "tailored" },
      status,
      source: "legacy",
    }],
  };
}

export function enrichPoolingCapability(
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
      const hasPools = Array.isArray(status.details?.pools);
      return hasPools
        ? provider
        : { ...provider, status: { ...status, details: legacyStatus.details } };
    }),
  };
}
